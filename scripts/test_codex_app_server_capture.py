#!/usr/bin/env python3
"""Offline security and protocol tests for app-server capture."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("codex_app_server_capture.py")
SPEC = importlib.util.spec_from_file_location("codex_app_server_capture", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(SCRIPT.parent))
from agent_eval import validate_materialized_workspace_manifest


class AppServerCaptureTests(unittest.TestCase):
    def test_capture_missing_manifest_returns_clean_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "capture.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = MODULE.main([
                    "capture", "--workspace", str(root / "missing-workspace"),
                    "--manifest", str(root / "missing-manifest.json"),
                    "--output", str(output),
                ])
            self.assertEqual(code, 2)
            self.assertIn('"error"', stderr.getvalue())
            self.assertNotIn("UnboundLocalError", stderr.getvalue())

    def test_workspace_allowlist_materializes_only_hashed_files_outside_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            root.mkdir()
            (root / "AGENTS.md").write_text("instruction", encoding="utf-8")
            (root / "case.txt").write_text("synthetic case", encoding="utf-8")
            (root / "docs/evaluations").mkdir(parents=True)
            (root / "docs/evaluations/rubric.json").write_text("holdout", encoding="utf-8")
            evidence = Path(temp) / "evidence"
            workspace, manifest = MODULE.prepare_workspace(root, "S-demo", ["AGENTS.md", "case.txt"], evidence)
            self.assertTrue(manifest["outside_repository"])
            self.assertFalse(manifest["git_present"])
            self.assertEqual({x["path"] for x in manifest["visible_files"]}, {"AGENTS.md", "case.txt"})
            self.assertFalse((workspace / "docs/evaluations").exists())
            MODULE.verify_workspace(workspace, json.loads(Path(manifest["manifest_path"]).read_text()))
            store = MODULE.EventStore()
            before = {"software-engineer": "a" * 64}
            after = dict(before)
            sources = [{"scope": "workspace", "sha256": "b" * 64}]
            event_hash = store.capture_event_sha256(manifest["run_id"], 1.25, before, after, sources)
            final_manifest = MODULE.finalize_workspace_manifest(Path(manifest["manifest_path"]), manifest, event_hash)
            record_evidence = {**final_manifest, "manifest_path": manifest["manifest_path"]}
            record = store.record(manifest["run_id"], 1.25, record_evidence, before, after, sources)
            final_payload = json.loads(Path(manifest["manifest_path"]).read_text())
            self.assertEqual(final_payload["generated_by"], "appserver_capture")
            self.assertEqual(final_payload["capture_event_sha256"], record["capture_event_sha256"])
            self.assertEqual(final_payload["run_id"], record["run_id"])
            self.assertTrue(final_payload["workspace"]["temporary"])
            self.assertTrue(Path(final_payload["workspace"]["root"]).is_absolute())
            self.assertFalse(final_payload["workspace"]["git_present"])
            self.assertEqual(record["safety"]["blinding_manifest"], record["safety"]["materialized_workspace_manifest"])
            self.assertEqual(record["safety"]["blinding_manifest"]["uri"], Path(manifest["manifest_path"]).name)
            self.assertEqual(record["safety"]["blinding_manifest"]["sha256"], MODULE.sha256(Path(manifest["manifest_path"]).read_bytes()))
            self.assertEqual(
                validate_materialized_workspace_manifest(
                    record["safety"]["materialized_workspace_manifest"],
                    Path(manifest["manifest_path"]).parent,
                    {"run_id": record["run_id"]},
                ),
                (True, "PASS"),
            )
            manifest_payload = Path(manifest["manifest_path"]).read_text()
            for secret in (str(root), "synthetic case"):
                self.assertNotIn(secret, manifest_payload)

    def test_workspace_rejects_traversal_symlinks_secrets_and_holdouts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "src"
            root.mkdir()
            (root / "safe.txt").write_text("ok")
            (root / "secret-token.txt").write_text("secret")
            (root / "link.txt").symlink_to(root / "safe.txt")
            with self.assertRaises(MODULE.CaptureError): MODULE._safe_relative("../escape")
            with self.assertRaises(MODULE.CaptureError): MODULE._safe_relative("docs/evaluations/case.json")
            with self.assertRaises(MODULE.CaptureError): MODULE.prepare_workspace(root, "x", ["secret-token.txt"], Path(temp) / "evidence")
            with self.assertRaises(MODULE.CaptureError): MODULE.prepare_workspace(root, "x", ["link.txt"], Path(temp) / "evidence")

    def test_runtime_workspace_filters_project_mcp_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            (root / ".codex").mkdir(parents=True)
            (root / "agents").mkdir()
            config = (
                '[features]\nmulti_agent = true\n'
                '[agents]\nenabled = true\n'
                '[agents.software-engineer]\nconfig_file = "../agents/software-engineer.toml"\n'
                '[mcp_servers.project-secret]\ncommand = "private-command"\n'
                '[mcp_servers.project-allowed]\ncommand = "allowed-command"\n'
            )
            (root / ".codex/config.toml").write_text(config, encoding="utf-8")
            (root / "agents/software-engineer.toml").write_text("name = 'worker'\n", encoding="utf-8")
            evidence = Path(temp) / "evidence"
            evidence.mkdir()
            source_workspace, manifest = MODULE.prepare_workspace(
                root, "MCP-case", [".codex/config.toml", "agents/software-engineer.toml"], evidence
            )
            runtime, runtime_manifest = MODULE.materialize_runtime_workspace(source_workspace, manifest, evidence, {"project-allowed"})
            source_config = (source_workspace / ".codex/config.toml").read_text(encoding="utf-8")
            runtime_config = (runtime / ".codex/config.toml").read_text(encoding="utf-8")
            self.assertIn("mcp_servers.project-secret", source_config)
            self.assertNotIn("mcp_servers.project-secret", runtime_config)
            self.assertIn("mcp_servers.project-allowed", runtime_config)
            self.assertIn("multi_agent = true", runtime_config)
            self.assertIn("agents/software-engineer.toml", runtime_manifest["visible_files"][1]["path"])
            self.assertEqual(runtime_manifest["workspace"]["root"], str(runtime.resolve()))
            runtime_root = runtime.parent
            MODULE.cleanup_owned_workspace(runtime, "codex-runtime-case-", Path(temp), manifest["run_id"])
            self.assertFalse(runtime_root.exists())
            victim_root = Path(temp) / "codex-runtime-case-victim"
            victim_workspace = victim_root / "workspace"
            victim_workspace.mkdir(parents=True)
            (victim_root / ".capture-owner").write_text("different-run\n", encoding="utf-8")
            MODULE.cleanup_owned_workspace(victim_workspace, "codex-runtime-case-", Path(temp), manifest["run_id"])
            self.assertTrue(victim_workspace.exists())

    def test_minimal_environment_keeps_provider_home_and_drops_secret_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "isolated-codex"
            codex_home.mkdir()
            (codex_home / "auth.json").write_text("synthetic-auth-reference", encoding="utf-8")
            audit = root / "env-audit.json"
            fake_server = root / "fake_app_server.py"
            fake_server.write_text(
                "import json,os,sys\n"
                "request=json.loads(sys.stdin.readline())\n"
                "with open(os.environ['AUDIT_FILE'],'w') as f: json.dump({'has_secret_marker':'CAPTURE_TEST_SECRET' in os.environ,'has_api_key':'OPENAI_API_KEY' in os.environ,'has_path':bool(os.environ.get('PATH')),'home':os.environ.get('CODEX_HOME'),'auth_exists':os.path.isfile(os.path.join(os.environ['CODEX_HOME'],'auth.json'))},f)\n"
                "print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{}}),flush=True)\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CAPTURE_TEST_SECRET": "do-not-pass", "OPENAI_API_KEY": "not-required", "AUDIT_FILE": str(audit)}):
                env = MODULE.build_app_server_env(codex_home)
            self.assertNotIn("CAPTURE_TEST_SECRET", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertIn("PATH", env)
            self.assertEqual(env["CODEX_HOME"], str(codex_home.resolve()))
            proc = subprocess.Popen([sys.executable, str(fake_server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={**env, "AUDIT_FILE": str(audit)})
            client = MODULE.JsonRpcClient(proc, timeout=2)
            try:
                client.request("initialize", {})
                proc.wait(timeout=2)
                result = json.loads(audit.read_text(encoding="utf-8"))
                self.assertFalse(result["has_secret_marker"])
                self.assertFalse(result["has_api_key"])
                self.assertTrue(result["has_path"])
                self.assertTrue(result["auth_exists"])
            finally:
                client.close()
                if proc.poll() is None: proc.terminate(); proc.wait(timeout=2)

    def test_protocol_retains_notification_before_response_and_after(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "server.py"
            fake.write_text(
                "import json,sys\n"
                "for line in sys.stdin:\n"
                " q=json.loads(line)\n"
                " if q.get('method') == 'initialize':\n"
                "  print(json.dumps({'jsonrpc':'2.0','method':'thread/started','params':{'thread':{'id':'private-thread','agentRole':'software-engineer','parentThreadId':'private-parent'}}}),flush=True)\n"
                "  print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':{}}),flush=True)\n"
                "  print(json.dumps({'jsonrpc':'2.0','method':'thread/tokenUsage/updated','params':{'tokenUsage':{'total':{'inputTokens':12,'outputTokens':3}}}}),flush=True)\n"
                " elif q.get('method') == 'stop': break\n",
                encoding="utf-8",
            )
            proc = subprocess.Popen([sys.executable, str(fake)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            client = MODULE.JsonRpcClient(proc, timeout=2)
            try:
                client.request("initialize", {})
                client.drain(0.2)
                record = client.store.record("fixture-run", 0.2, {}, {}, {}, [])
                self.assertEqual(record["agent_identity_status"], "OBSERVED")
                self.assertEqual(record["usage_status"], "OBSERVED")
                encoded = json.dumps(record)
                for private in ("private-thread", "private-parent"):
                    self.assertNotIn(private, encoded)
                self.assertIn(MODULE.thread_hash("private-thread"), encoded)
                self.assertEqual(client.store.usage["inputTokens"], 12)
            finally:
                client.close()
                proc.terminate(); proc.wait(timeout=2)

    def test_event_redaction_and_missing_identity_or_usage_stays_pending(self):
        store = MODULE.EventStore()
        store.consume({"method":"thread/started","params":{"thread":{"id":"raw-id","agentRole":"worker","parentThreadId":"parent"}}})
        store.consume({"method":"item/started","params":{"item":{"type":"collabAgentToolCall","tool":"spawnAgent","prompt":"secret prompt","arguments":{"token":"secret"}}}})
        record = store.record("r", 1.0, {}, {}, {}, [])
        encoded = json.dumps(record)
        for secret in ("raw-id", '"parent"', "secret prompt", '"token": "secret"'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(record["usage_status"], "PENDING")
        self.assertEqual(record["agent_identity_status"], "OBSERVED")
        self.assertEqual(record["evaluation_status"], "PENDING")
        missing = MODULE.EventStore().record("r", 1.0, {}, {}, {}, [])
        self.assertEqual(missing["agent_identity_status"], "PENDING")
        self.assertEqual(missing["usage_status"], "PENDING")

    def test_turn_completion_and_bad_usage(self):
        store = MODULE.EventStore()
        store.consume({"method":"turn/completed","params":{}})
        self.assertEqual(store.status, "completed")
        with self.assertRaises(MODULE.CaptureError):
            store.consume({"method":"thread/tokenUsage/updated","params":{"tokenUsage":{"total":{"inputTokens":True}}}})

    def test_mcp_filter_is_empty_by_default_and_preserves_agent_roles(self):
        config = '''model = "gpt-6-luna"\n[agents]\nenabled = true\n[agents.software-engineer]\nconfig_file = "../agents/software-engineer.toml"\n[mcp_servers.secret]\ncommand = "private"\n[mcp_servers.allowed]\ncommand = "safe"\n'''
        filtered = MODULE.strip_mcp_tables(config)
        self.assertNotIn("mcp_servers", filtered)
        self.assertIn("software-engineer.toml", filtered)
        self.assertIn("enabled = true", filtered)
        allowed = MODULE.strip_mcp_tables(config, {"allowed"})
        self.assertNotIn("mcp_servers.secret", allowed)
        self.assertIn("mcp_servers.allowed", allowed)
        with self.assertRaises(MODULE.CaptureError):
            MODULE.strip_mcp_tables('mcp_servers = { x = {} }\n')

    def test_mcp_allowlist_preserves_allowed_subtables_and_removes_denied_subtables(self):
        config = '''[mcp_servers.foo]\ncommand = "foo-command"\n[mcp_servers.foo.env]\nTOKEN = "foo-token"\n[mcp_servers.bar]\ncommand = "bar-command"\n[mcp_servers.bar.env]\nTOKEN = "bar-token"\n[mcp_servers."foo.bar"]\ncommand = "dotted-command"\n[mcp_servers."foo.bar".env]\nTOKEN = "dotted-token"\n'''
        filtered = MODULE.strip_mcp_tables(config, {"foo", "foo.bar"})
        self.assertIn("[mcp_servers.foo.env]", filtered)
        self.assertIn('TOKEN = "foo-token"', filtered)
        self.assertNotIn("mcp_servers.bar", filtered)
        self.assertNotIn("bar-token", filtered)
        self.assertIn('[mcp_servers."foo.bar".env]', filtered)
        self.assertIn('TOKEN = "dotted-token"', filtered)

    def test_mcp_root_assignments_fail_closed_with_allowlist(self):
        config = '''[mcp_servers]\nunsafe = { command = "bad", args = ["run"] }\n[mcp_servers.foo]\ncommand = "allowed-command"\n'''
        with self.assertRaisesRegex(MODULE.CaptureError, "root MCP table"):
            MODULE.strip_mcp_tables(config, {"foo"})
        filtered = MODULE.strip_mcp_tables(config, set())
        self.assertNotIn("mcp_servers", filtered)
        self.assertNotIn("unsafe", filtered)
        self.assertNotIn("bad", filtered)
        self.assertNotIn("run", filtered)

    def test_root_inline_quoted_dotted_and_multiline_mcp_assignments_fail_closed(self):
        unsafe_configs = [
            '"mcp_servers" = { evil = { command = "echo", args = ["run"] } }\n',
            'mcp_servers.evil.command = "echo"\nmcp_servers.evil.args = ["run"]\n',
            'mcp_servers = [\n  { name = "evil", command = "echo", args = ["run"] },\n]\n',
        ]
        for config in unsafe_configs:
            with self.subTest(config=config):
                for allow in (set(), {"safe"}):
                    with self.assertRaisesRegex(MODULE.CaptureError, "root MCP assignments"):
                        MODULE.strip_mcp_tables(config, allow)

    def test_isolated_home_filters_user_mcp_without_mutating_config(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex"
            home.mkdir()
            source = home / "config.toml"
            source.write_text('[mcp_servers.external]\ncommand = "private"\n[agents]\nenabled = true\n', encoding="utf-8")
            auth = home / "auth.json"
            auth.write_text('{"access_token":"private"}', encoding="utf-8")
            with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
                overlay = MODULE.isolated_codex_home(set())
            try:
                self.assertNotIn("mcp_servers", (overlay / "config.toml").read_text())
                self.assertTrue((overlay / "auth.json").is_symlink())
                self.assertIn("private", source.read_text())
            finally:
                import shutil
                shutil.rmtree(overlay)

    def test_rpc_timeout_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "server.py"
            fake.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, str(fake)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            client = MODULE.JsonRpcClient(proc, timeout=0.1)
            try:
                with self.assertRaises(TimeoutError): client.request("initialize", {})
            finally:
                client.close()
                proc.terminate(); proc.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()

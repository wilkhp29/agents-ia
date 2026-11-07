#!/usr/bin/env python3
"""Security and behavior tests for the Codex JSONL minimizer."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("codex_runtime_capture.py")
SPEC = importlib.util.spec_from_file_location("codex_runtime_capture", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def event(kind: str, **fields: object) -> str:
    return json.dumps({"type": kind, **fields})


class RuntimeCaptureTests(unittest.TestCase):
    def test_exec_args_register_project_roles_via_cli_overrides(self):
        roles = MODULE.load_project_roles()
        args = MODULE.build_exec_args(roles, executable="codex", sandbox="read-only")
        rendered = " ".join(args)
        self.assertIn("--enable", args)
        self.assertIn("multi_agent", args)
        self.assertIn("agents.intake-normalizer.config_file=", rendered)
        self.assertIn("agents.intake-normalizer.description=", rendered)
        self.assertIn(str((MODULE.ROOT / "agents/intake-normalizer.toml").resolve()), rendered)

    def test_extracts_only_minimized_usage_and_handoff_counts(self):
        rows = [
            event("thread.started", thread_id="thread-raw-sensitive-id"),
            event("turn.started"),
            event("item.started", item={"id": "item-1", "type": "collab_tool_call", "tool": "spawn_agent", "prompt": "private user seed", "sender_thread_id": "secret-thread"}),
            event("item.started", item={"id": "item-2", "type": "mcp_tool_call", "arguments": {"api_key": "sk-secret"}, "result": "private tool response"}),
            event("item.completed", item={"id": "item-3", "type": "agent_message", "text": "Synthetic final answer"}),
            event("turn.completed", usage={"input_tokens": 17, "output_tokens": 9, "cached_input_tokens": 4, "reasoning_output_tokens": 2}),
        ]
        capture = MODULE.parse_stream(rows, task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=1.25)
        encoded = json.dumps(capture.metric)
        for secret in ("thread-raw-sensitive-id", "private user seed", "secret-thread", "sk-secret", "private tool response", "Synthetic final answer"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(capture.metric["tokens_input"], 17)
        self.assertEqual(capture.metric["tokens_output"], 9)
        self.assertEqual(capture.metric["cached_tokens_input"], 4)
        self.assertEqual(capture.metric["reasoning_tokens_output"], 2)
        self.assertEqual(capture.metric["agent_spawn_calls"], 1)
        self.assertEqual(capture.metric["collaboration_tool_calls"], 1)
        self.assertEqual(capture.metric["agent_spawn_completed"], 0)
        self.assertEqual(capture.metric["agent_dispatches_observed"], 0)
        self.assertFalse(capture.metric["profile_identity_verified"])
        self.assertEqual(capture.final_message, "Synthetic final answer")

    def test_collaboration_counters_cover_v1_and_namespaced_v2_events(self):
        rows = [
            event("thread.started", thread_id="thread-parent"),
            event("item.started", item={"id":"spawn-v1","type":"collab_tool_call","tool":"spawn_agent","prompt":"private request"}),
            event("item.completed", item={"id":"spawn-v1","type":"collab_tool_call","tool":"spawn_agent","status":"failed","receiver_thread_ids":[],"prompt":"private request"}),
            event("item.started", item={"id":"spawn-v2","type":"function_call","namespace":"collaboration","name":"spawn_agent","arguments":{"prompt":"private v2 request"}}),
            event("item.completed", item={"id":"spawn-v2","type":"function_call","namespace":"collaboration","name":"spawn_agent","status":"completed","receiver_thread_ids":["child-private-id"]}),
            event("turn.completed", usage={}),
        ]
        capture = MODULE.parse_stream(rows, task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=1.0)
        metric = capture.metric
        self.assertEqual(metric["collaboration_tool_calls"], 2)
        self.assertEqual(metric["agent_spawn_calls"], 2)
        self.assertEqual(metric["agent_spawn_completed"], 1)
        self.assertEqual(metric["agent_spawn_failures"], 1)
        self.assertEqual(metric["agent_dispatches_observed"], 1)
        serialized = json.dumps(metric)
        for private in ("private request", "private v2 request", "child-private-id"):
            self.assertNotIn(private, serialized)

    def test_wait_completion_observes_new_agent_thread_without_double_counting(self):
        rows = [
            event("thread.started", thread_id="thread-parent"),
            event("item.completed", item={"id":"spawn","type":"collab_tool_call","tool":"spawn_agent","status":"completed","receiver_thread_ids":["child-private-id"]}),
            event("item.completed", item={"id":"wait","type":"collab_tool_call","tool":"wait","status":"completed","receiver_thread_ids":["child-private-id"]}),
            event("turn.completed", usage={}),
        ]
        capture = MODULE.parse_stream(rows, task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=1.0)
        self.assertEqual(capture.metric["agent_spawn_completed"], 1)
        self.assertEqual(capture.metric["agent_dispatches_observed"], 1)
        self.assertNotIn("child-private-id", json.dumps(capture.metric))

    def test_hashed_run_id_does_not_reveal_thread_id(self):
        capture = MODULE.parse_stream(
            [event("thread.started", thread_id="thread-private"), event("turn.completed", usage={})],
            task_size="unknown", runtime_version="codex-cli 0.166.0", duration_seconds=0.1,
        )
        self.assertRegex(capture.metric["run_id"], r"^run_[0-9a-f]{24}$")
        self.assertNotIn("thread-private", json.dumps(capture.metric))

    def test_unknown_event_is_dropped_without_echoing_payload(self):
        capture = MODULE.parse_stream(
            [event("thread.started", thread_id="t"), event("future.secret", value="must-not-leak"), event("turn.completed", usage={})],
            task_size="medium", runtime_version="codex-cli 0.166.0", duration_seconds=0.1,
        )
        self.assertEqual(capture.metric["unknown_events"], 1)
        self.assertNotIn("must-not-leak", json.dumps(capture.metric))

    def test_malformed_json_fails_without_echoing_input(self):
        with self.assertRaises(MODULE.CaptureError) as caught:
            MODULE.parse_stream(["{\"type\":\"bad\",\"secret\":\"leak-me\""], task_size="unknown", runtime_version="codex-cli 0.166.0", duration_seconds=0.1)
        self.assertNotIn("leak-me", str(caught.exception))

    def test_invalid_usage_fails_closed(self):
        for usage in ({"input_tokens": -1}, {"input_tokens": True}, {"output_tokens": 1e100}, []):
            with self.subTest(usage=usage), self.assertRaises(MODULE.CaptureError):
                MODULE.parse_stream([event("thread.started", thread_id="t"), event("turn.completed", usage=usage)], task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=0.1)

    def test_requires_thread_id_and_terminal_turn_event(self):
        with self.assertRaises(MODULE.CaptureError):
            MODULE.parse_stream([event("thread.started", thread_id="")], task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=0.1)
        with self.assertRaises(MODULE.CaptureError):
            MODULE.parse_stream([event("thread.started", thread_id="t")], task_size="small", runtime_version="codex-cli 0.166.0", duration_seconds=0.1)
        config = __import__("tomllib").loads((MODULE.ROOT / ".codex/config.toml").read_text())
        self.assertIs(config.get("features", {}).get("multi_agent"), True)

    def test_runtime_metric_schema_role_mapping_matches_profile_files(self):
        config = MODULE.load_project_roles()
        self.assertEqual(set(config), MODULE.PROJECT_ROLES)
        for role, relative in config.items():
            target = (MODULE.ROOT / ".codex" / relative).resolve()
            self.assertTrue(target.is_relative_to(MODULE.ROOT.resolve()))
            self.assertTrue(target.is_file(), role)

    def test_timeout_kills_fake_cli_and_persists_only_partial_metrics(self):
        with tempfile.TemporaryDirectory(dir=MODULE.ROOT) as temp:
            folder = Path(temp)
            fake_cli = folder / "codex"
            fake_cli.write_text(
                f"#!{sys.executable}\n"
                "import json,os,sys,time\n"
                "if sys.argv[1:] == ['--version']:\n"
                " print('codex-cli 0.166.0'); raise SystemExit(0)\n"
                "if '--ignore-user-config' not in sys.argv or '--enable' not in sys.argv or 'multi_agent' not in sys.argv: raise SystemExit(95)\n"
                "print(json.dumps({'type':'thread.started','thread_id':'private-thread-id'}), flush=True)\n"
                "os.close(1)\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            fake_cli.chmod(0o700)
            ledger = folder / "metrics.jsonl"
            with patch.dict(os.environ, {"PATH": f"{folder}:{os.environ.get('PATH','')}"}), patch.object(MODULE, "METRICS_PATH", ledger):
                started = time.monotonic()
                with self.assertRaises(MODULE.CaptureError) as caught:
                    MODULE.run_prompt(b"synthetic prompt", task_size="small", timeout_seconds=1)
                self.assertLess(time.monotonic() - started, 6)
            self.assertIn("timed out", str(caught.exception))
            record = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "timed_out")
            self.assertFalse(record["profile_identity_verified"])
            self.assertNotIn("private-thread-id", ledger.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic prompt", ledger.read_text(encoding="utf-8"))

    def test_failed_turn_persists_minimized_metrics(self):
        with tempfile.TemporaryDirectory(dir=MODULE.ROOT) as temp:
            folder = Path(temp)
            fake_cli = folder / "codex"
            fake_cli.write_text(
                f"#!{sys.executable}\n"
                "import json,sys\n"
                "if sys.argv[1:] == ['--version']:\n"
                " print('codex-cli 0.166.0'); raise SystemExit(0)\n"
                "print(json.dumps({'type':'thread.started','thread_id':'private-failed-thread'}), flush=True)\n"
                "print(json.dumps({'type':'turn.started'}), flush=True)\n"
                "print(json.dumps({'type':'turn.failed','error':{'message':'private failure details'}}), flush=True)\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            fake_cli.chmod(0o700)
            ledger = folder / "metrics.jsonl"
            with patch.dict(os.environ, {"PATH": f"{folder}:{os.environ.get('PATH','')}"}), patch.object(MODULE, "METRICS_PATH", ledger):
                with self.assertRaises(MODULE.CaptureError):
                    MODULE.run_prompt(b"synthetic private prompt", task_size="small", timeout_seconds=3)
            encoded = ledger.read_text(encoding="utf-8")
            record = json.loads(encoded)
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["failures"], 1)
            for private in ("private-failed-thread", "private failure details", "synthetic private prompt"):
                self.assertNotIn(private, encoded)

    def test_timeout_limit_is_rejected_before_process_start(self):
        with self.assertRaises(MODULE.CaptureError):
            MODULE.run_prompt(b"synthetic", task_size="small", timeout_seconds=MODULE.MAX_TIMEOUT_SECONDS + 1)


if __name__ == "__main__":
    unittest.main()

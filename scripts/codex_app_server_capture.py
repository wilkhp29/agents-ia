#!/usr/bin/env python3
"""Privacy-minimized Codex app-server capture and isolated case workspace helper.

Default operation only reads app-server config. A model turn requires explicit
--run --allow-model-usage and a prepared, blinded workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
try:
    import tomllib
except ImportError:  # Python 3.9/3.10 may use the tomli backport.
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_LINE = 1024 * 1024
MAX_EVENTS = 20000
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_TIMEOUT = 300
MAX_COUNTER = 10**12
EXCLUDED = [".git", "docs/evaluations", "rubric", "holdout", "*.env", "*.pem", "*.key"]
EVALUATION_EXCLUSIONS = [
    "docs/evaluations",
    "docs/evaluations/delivery-size-v1.json",
    "docs/evaluations/delivery-size-v1-rubric.json",
]
SECRET_NAME = re.compile(r"(^|[._-])(secret|credential|token|password|private[-_]?key)([._-]|$)", re.I)

class CaptureError(ValueError):
    """Safe error text; never include protocol payloads."""

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def thread_hash(value: str) -> str:
    return "thread_" + sha256(value.encode())[:24]

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise CaptureError("allowlist path must be a normalized relative path")
    lowered = value.lower()
    if any(x in lowered for x in ("docs/evaluations", "rubric", "holdout")) or path.parts[0] == ".git":
        raise CaptureError("evaluation and repository metadata paths are excluded")
    if SECRET_NAME.search(path.name) or path.name.lower() in {".env", "id_rsa", "id_ed25519"}:
        raise CaptureError("secret-like files are excluded")
    return path

def prepare_workspace(source: Path, case_id: str, allowed: list[str], evidence_dir: Path) -> tuple[Path, dict[str, Any]]:
    source = source.resolve(strict=True)
    evidence_dir = evidence_dir.resolve()
    if source == evidence_dir or source in evidence_dir.parents or evidence_dir in source.parents:
        raise CaptureError("workspace and evidence directory must be separate")
    if not allowed or len(set(allowed)) != len(allowed):
        raise CaptureError("a unique non-empty file allowlist is required")
    files: list[tuple[PurePosixPath, bytes]] = []
    total = 0
    for raw in allowed:
        rel = _safe_relative(raw)
        target = source.joinpath(*rel.parts)
        if target.is_symlink() or not target.is_file():
            raise CaptureError("allowlist entries must be regular files without symlinks")
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(source):
            raise CaptureError("allowlist entry escapes the source workspace")
        data = resolved.read_bytes()
        if len(data) > MAX_FILE:
            raise CaptureError("allowlist file exceeds the size limit")
        total += len(data)
        if total > MAX_TOTAL:
            raise CaptureError("allowlist exceeds the total size limit")
        files.append((rel, data))
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_dir.chmod(0o700)
    temp_root = Path(tempfile.mkdtemp(prefix="codex-case-", dir=evidence_dir.parent))
    workspace = temp_root / "workspace"
    workspace.mkdir(mode=0o700)
    visible: list[dict[str, str]] = []
    for rel, data in files:
        dest = workspace.joinpath(*rel.parts)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest.write_bytes(data)
        dest.chmod(0o600)
        visible.append({"path": rel.as_posix(), "sha256": sha256(data)})
    if (workspace / ".git").exists() or (workspace / "docs/evaluations").exists():
        shutil.rmtree(temp_root, ignore_errors=True)
        raise CaptureError("materialized workspace contains excluded evaluation data")
    run_id = str(uuid.uuid4())
    (temp_root / ".capture-owner").write_text(run_id + "\n", encoding="utf-8")
    (temp_root / ".capture-owner").chmod(0o600)
    manifest = {
        "schema_version": 1, "run_id": run_id, "case_id": case_id,
        "generated_by": "appserver_capture", "capture_event_sha256": None,
        "workspace_type": "temp_materialized", "outside_repository": not workspace.is_relative_to(ROOT.resolve()),
        "git_present": (workspace / ".git").exists(), "visible_files": visible,
        "excluded_evaluation_paths": EXCLUDED, "excluded_paths": EVALUATION_EXCLUSIONS,
        "workspace": {"root": str(workspace.resolve()), "temporary": True, "git_present": False},
        "workspace_sha256": sha256(json.dumps(visible, sort_keys=True, separators=(",", ":")).encode()),
    }
    if not manifest["outside_repository"] or manifest["git_present"]:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise CaptureError("isolated workspace invariant failed")
    manifest_path = evidence_dir / f"{run_id}-blinding-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    return workspace, {**manifest, "manifest_path": str(manifest_path)}

def verify_workspace(workspace: Path, manifest: dict[str, Any]) -> None:
    workspace = workspace.resolve(strict=True)
    if manifest.get("workspace_type") != "temp_materialized" or manifest.get("outside_repository") is not True or manifest.get("git_present") is not False:
        raise CaptureError("blinding manifest does not prove an isolated workspace")
    if workspace.is_relative_to(ROOT.resolve()) or (workspace / ".git").exists() or (workspace / "docs/evaluations").exists():
        raise CaptureError("workspace is not blinded or lies inside the repository")
    expected = manifest.get("visible_files")
    if not isinstance(expected, list) or not expected:
        raise CaptureError("manifest visible file inventory is missing")
    actual_paths = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file())
    if actual_paths != sorted(item.get("path") for item in expected if isinstance(item, dict)):
        raise CaptureError("workspace inventory differs from its manifest")
    for item in expected:
        p = _safe_relative(item["path"])
        target = workspace.joinpath(*p.parts)
        if target.is_symlink() or sha256(target.read_bytes()) != item.get("sha256"):
            raise CaptureError("workspace content differs from its manifest")

def materialize_runtime_workspace(source: Path, manifest: dict[str, Any], evidence_dir: Path, allowed_mcp: set[str]) -> tuple[Path, dict[str, Any]]:
    """Copy only approved files and strip project MCP config in a temporary overlay."""
    source = source.resolve(strict=True)
    evidence_dir = evidence_dir.resolve(strict=True)
    if source.is_relative_to(ROOT.resolve()) or evidence_dir.is_relative_to(ROOT.resolve()):
        raise CaptureError("runtime and evidence workspaces must remain outside the repository")
    runtime_root = Path(tempfile.mkdtemp(prefix="codex-runtime-case-", dir=evidence_dir.parent))
    (runtime_root / ".capture-owner").write_text(str(manifest.get("run_id", "")) + "\n", encoding="utf-8")
    (runtime_root / ".capture-owner").chmod(0o600)
    runtime = runtime_root / "workspace"
    runtime.mkdir(mode=0o700)
    visible: list[dict[str, str]] = []
    for item in manifest.get("visible_files", []):
        rel = _safe_relative(item.get("path", ""))
        original = source.joinpath(*rel.parts)
        if original.is_symlink() or not original.is_file():
            shutil.rmtree(runtime_root, ignore_errors=True)
            raise CaptureError("runtime allowlist source is missing or unsafe")
        data = original.read_bytes()
        if sha256(data) != item.get("sha256"):
            shutil.rmtree(runtime_root, ignore_errors=True)
            raise CaptureError("runtime allowlist source hash changed")
        if rel.as_posix() == ".codex/config.toml":
            if tomllib is None:
                shutil.rmtree(runtime_root, ignore_errors=True)
                raise CaptureError("TOML parser is required (Python 3.11+ or tomli)")
            data = strip_mcp_tables(data.decode("utf-8"), allowed_mcp).encode("utf-8")
        target = runtime.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        target.chmod(0o600)
        visible.append({"path": rel.as_posix(), "sha256": sha256(data)})
    if not (runtime / ".codex/config.toml").is_file():
        shutil.rmtree(runtime_root, ignore_errors=True)
        raise CaptureError("isolated workspace must include its project Codex config")
    updated = {
        **manifest,
        "visible_files": visible,
        "workspace_sha256": sha256(json.dumps(visible, sort_keys=True, separators=(",", ":")).encode()),
        "outside_repository": True,
        "git_present": False,
        "workspace": {"root": str(runtime.resolve()), "temporary": True, "git_present": False},
    }
    return runtime, updated

def cleanup_owned_workspace(workspace: Path, prefix: str, expected_parent: Path, run_id: str) -> None:
    """Delete only a matching, sentinel-owned temp directory under the expected parent."""
    resolved = workspace.resolve()
    temp_root = resolved.parent
    sentinel = temp_root / ".capture-owner"
    try:
        owner = sentinel.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if (
        resolved.name == "workspace"
        and temp_root.name.startswith(prefix)
        and temp_root.parent == expected_parent.resolve()
        and owner == run_id
    ):
        shutil.rmtree(resolved.parent, ignore_errors=True)

def finalize_workspace_manifest(path: Path, manifest: dict[str, Any], capture_event_sha256: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", capture_event_sha256):
        raise CaptureError("sanitized capture event hash is invalid")
    required = {
        "schema_version": 1,
        "generated_by": "appserver_capture",
        "run_id": manifest.get("run_id"),
        "capture_event_sha256": capture_event_sha256,
        "workspace": manifest.get("workspace"),
        "visible_files": manifest.get("visible_files"),
        "excluded_paths": EVALUATION_EXCLUSIONS,
    }
    result = {**manifest, **required}
    result.pop("manifest_path", None)
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return result

def strip_mcp_tables(config_text: str, allow: set[str] | None = None) -> str:
    """Remove MCP tables while preserving all other TOML; fail closed on inline form."""
    if tomllib is None:
        raise CaptureError("TOML parser is required (Python 3.11+ or tomli)")
    try:
        config = tomllib.loads(config_text)
    except tomllib.TOMLDecodeError as exc:
        raise CaptureError("Codex config is invalid TOML") from exc
    # Root assignments can encode arbitrary MCP providers inline or with dotted
    # keys; unlike provider tables, they cannot be filtered safely by allowlist.
    lines = config_text.splitlines(keepends=True)
    first_header = next((i for i, line in enumerate(lines) if _parse_table_header(line) is not None), len(lines))
    try:
        root_assignments = tomllib.loads("".join(lines[:first_header]))
    except tomllib.TOMLDecodeError as exc:
        raise CaptureError("root Codex config assignments cannot be safely parsed") from exc
    if "mcp_servers" in root_assignments:
        raise CaptureError("root MCP assignments cannot be safely allowlisted")
    # Parse headers with TOML itself so dotted keys inside quotes are not split.
    sections: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        parsed = _parse_table_header(line)
        if parsed is not None:
            sections.append((i, len(lines), parsed[0]))
    for idx in range(len(sections) - 1):
        start, _, name = sections[idx]
        sections[idx] = (start, sections[idx + 1][0], name)
    remove: set[int] = set()
    for start, end, name in sections:
        server = _mcp_server_for_header(name)
        if server is not False:
            if server is None:
                has_root_assignments = any(
                    line.strip() and not line.lstrip().startswith("#")
                    for line in lines[start + 1:end]
                )
                if allow and has_root_assignments:
                    raise CaptureError("root MCP table contains entries that cannot be safely allowlisted")
                remove.update(range(start, end))
            elif allow is None or server not in allow:
                remove.update(range(start, end))
    result = "".join(line for i, line in enumerate(lines) if i not in remove)
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise CaptureError("filtered Codex config is invalid") from exc
    return result

def _parse_table_header(line: str) -> tuple[str, bool] | None:
    stripped = line.strip()
    array = stripped.startswith("[[")
    opening = 2 if array else 1
    if len(stripped) <= opening or stripped[0] != "[":
        return None
    in_basic = False
    in_literal = False
    escaped = False
    closing = None
    i = opening
    while i < len(stripped):
        char = stripped[i]
        if in_basic:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == '"': in_basic = False
        elif in_literal:
            if char == "'": in_literal = False
        elif char == '"': in_basic = True
        elif char == "'": in_literal = True
        elif char == "]":
            closing = i
            break
        i += 1
    if closing is None:
        return None
    if array:
        if stripped[closing:closing+2] != "]]": return None
        tail = stripped[closing+2:]
    else:
        tail = stripped[closing+1:]
    if tail.strip() and not tail.lstrip().startswith("#"):
        return None
    expression = stripped[opening:closing].strip()
    return (expression, array) if expression else None

def _mcp_server_for_header(expression: str) -> str | None | bool:
    """Return server key, None for the mcp_servers root, False for other tables."""
    if tomllib is None: return False
    try:
        parsed = tomllib.loads(f"[{expression}]\n")
    except tomllib.TOMLDecodeError:
        return False
    mcp = parsed.get("mcp_servers")
    if not isinstance(mcp, dict): return False
    if not mcp: return None
    return next(iter(mcp))

class EventStore:
    """Stores only allowlisted app-server metadata; discards raw protocol bodies."""
    def __init__(self) -> None:
        self.events = 0
        self.threads: dict[str, dict[str, Any]] = {}
        self.usage_seen = False
        self.usage: dict[str, int] = {}
        self.started_at: str | None = None
        self.status = "PENDING"
        self.model: str | None = None
        self.version: str | None = None
        self.spawn_calls = 0
        self.failures = 0

    def consume(self, message: dict[str, Any]) -> None:
        self.events += 1
        if self.events > MAX_EVENTS:
            raise CaptureError("app-server event limit exceeded")
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if method == "thread/started":
            thread = params.get("thread")
            if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
                return
            tid = thread_hash(thread["id"])
            role = thread.get("agentRole")
            parent = thread.get("parentThreadId")
            self.threads[tid] = {"thread_id": tid, "role": role if isinstance(role, str) else None,
                                 "parent_thread_id": thread_hash(parent) if isinstance(parent, str) else None,
                                 "status": "started", "started_at": now()}
            self.started_at = self.started_at or now()
        elif method == "thread/tokenUsage/updated":
            info = params.get("tokenUsage") or params.get("token_usage") or params
            totals = info.get("total") if isinstance(info, dict) else None
            if isinstance(totals, dict):
                sanitized = {}
                for key in ("inputTokens", "outputTokens", "cachedInputTokens", "reasoningOutputTokens", "input_tokens", "output_tokens"):
                    value = totals.get(key)
                    if value is not None:
                        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNTER:
                            raise CaptureError("invalid token usage counter")
                        sanitized[key] = value
                if sanitized:
                    self.usage_seen = True
                    self.usage.update(sanitized)
        elif method in {"turn/completed", "turn/complete"}:
            self.status = "completed"
        elif method in {"thread/closed", "thread/finished"}:
            tid = params.get("threadId") or params.get("thread_id")
            if isinstance(tid, str) and thread_hash(tid) in self.threads:
                self.threads[thread_hash(tid)]["status"] = "completed"
        elif method == "item/started":
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "collabAgentToolCall":
                if item.get("tool") == "spawnAgent": self.spawn_calls += 1
        elif method in {"turn/failed", "error"}:
            self.failures += 1
            self.status = "failed"

    def capture_event_sha256(self, run_id: str, duration: float, profile_before: dict[str, str], profile_after: dict[str, str], instruction_hashes: list[dict[str, str]]) -> str:
        """Hash a canonical, minimized event snapshot before adding manifest evidence."""
        payload = {
            "run_id": run_id,
            "status": self.status,
            "duration_seconds": round(duration, 3),
            "model": self.model,
            "runtime_version": self.version,
            "threads": self.threads,
            "tokens": self.usage if self.usage_seen else None,
            "usage_status": "OBSERVED" if self.usage_seen else "PENDING",
            "agent_identity_status": "OBSERVED" if any(t.get("role") and t.get("parent_thread_id") for t in self.threads.values()) else "PENDING",
            "spawn_calls": self.spawn_calls,
            "profile_sha256_before": profile_before,
            "profile_sha256_after": profile_after,
            "instruction_sources": instruction_hashes,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(raw)

    def record(self, run_id: str, duration: float, workspace_evidence: dict[str, Any], profile_before: dict[str, str], profile_after: dict[str, str], instruction_hashes: list[dict[str,str]]) -> dict[str, Any]:
        children = [t for t in self.threads.values() if t.get("role")]
        identity = bool(children) and all(t.get("parent_thread_id") for t in children)
        manifest_path = workspace_evidence.get("manifest_path")
        manifest_ref = None
        if isinstance(manifest_path, str):
            try: manifest_ref = {"uri": Path(manifest_path).name, "sha256": sha256(Path(manifest_path).read_bytes())}
            except OSError: manifest_ref = None
        return {
            "schema_version": 1, "source": "codex_app_server", "run_id": run_id,
            "status": self.status if self.status != "PENDING" else ("completed" if self.started_at else "PENDING"),
            "started_at": self.started_at, "captured_at": now(), "duration_seconds": round(duration, 3),
            "model": self.model, "runtime_version": self.version, "tokens": self.usage if self.usage_seen else None,
            "cost": None, "cost_status": "N/A_chatgpt_plan", "threads": list(self.threads.values()),
            "evaluation_status": "PENDING",
            "evaluation_reason": "capture evidence is not yet converted into an evaluator trial/runtime record",
            "agent_identity_status": "OBSERVED" if identity else "PENDING",
            "usage_status": "OBSERVED" if self.usage_seen else "PENDING", "spawn_calls": self.spawn_calls,
            "profile_sha256_before": profile_before, "profile_sha256_after": profile_after,
            "profile_hashes_match": profile_before == profile_after,
            "capture_event_sha256": workspace_evidence.get("capture_event_sha256"),
            "resolved_role_config": workspace_evidence.get("resolved_role_config", {}),
            "instruction_sources": instruction_hashes,
            "safety": {"blinding_manifest": manifest_ref, "materialized_workspace_manifest": manifest_ref, "workspace": {k: workspace_evidence.get(k) for k in ("workspace_type","outside_repository","git_present","visible_files","excluded_evaluation_paths","workspace_sha256")},
                       "identity_evidence": "observed runtime role/parent plus effective config path/hash; not cryptographic attestation"},
        }

class JsonRpcClient:
    """Line-delimited JSON-RPC client retaining interleaved server events."""
    def __init__(self, process: subprocess.Popen[bytes], timeout: float = 30) -> None:
        self.process, self.timeout = process, timeout
        self.selector = selectors.DefaultSelector()
        assert process.stdout
        self.selector.register(process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.eof = False
        self.next_id = 1
        self.store = EventStore()

    def _read_message(self, deadline: float) -> dict[str, Any]:
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("app-server request timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)  # type: ignore[union-attr]
            if not chunk:
                self.eof = True
                raise CaptureError("app-server closed its protocol stream")
            self.buffer += chunk
            if len(self.buffer) > MAX_LINE and b"\n" not in self.buffer:
                raise CaptureError("app-server message exceeds the size limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        if len(line) > MAX_LINE:
            raise CaptureError("app-server message exceeds the size limit")
        try: obj = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise CaptureError("invalid app-server message") from exc
        if not isinstance(obj, dict): raise CaptureError("invalid app-server message")
        return obj

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id; self.next_id += 1
        payload = json.dumps({"jsonrpc":"2.0","id":request_id,"method":method,"params":params}, separators=(",", ":")).encode()+b"\n"
        assert self.process.stdin
        self.process.stdin.write(payload); self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            msg = self._read_message(deadline)
            if "method" in msg and "id" in msg:
                self.process.stdin.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"error":{"code":-32601,"message":"unsupported"}}).encode()+b"\n"); self.process.stdin.flush()
                continue
            if "method" in msg:
                self.store.consume(msg)
                continue
            if msg.get("id") == request_id:
                if "error" in msg: raise CaptureError("app-server request failed")
                result = msg.get("result")
                if not isinstance(result, dict): raise CaptureError("app-server response is invalid")
                return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        assert self.process.stdin
        payload = json.dumps({"jsonrpc":"2.0","method":method,"params":params},separators=(",", ":")).encode()+b"\n"
        self.process.stdin.write(payload); self.process.stdin.flush()

    def drain(self, seconds: float = 0) -> None:
        deadline = time.monotonic() + seconds
        while b"\n" in self.buffer or self.selector.select(max(0, deadline-time.monotonic())):
            try: self.store.consume(self._read_message(time.monotonic()+0.1))
            except CaptureError:
                if self.eof: return
                raise

    def close(self) -> None:
        try: self.selector.close()
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    try: stream.close()
                    except OSError: pass

def profile_hashes(root: Path, config: dict[str, Any]) -> dict[str, str]:
    out = {}
    agents = config.get("agents", {})
    for role, value in agents.items():
        if role in {"enabled","max_concurrent_threads_per_session","max_depth","default_subagent_model","default_subagent_reasoning_effort"} or not isinstance(value, dict): continue
        rel = value.get("config_file")
        if not isinstance(rel, str): continue
        path = (root / ".codex" / rel).resolve()
        if path.is_relative_to(root.resolve()) and path.is_file(): out[role] = sha256(path.read_bytes())
    return out

def profile_paths(root: Path, config: dict[str, Any]) -> dict[str, str]:
    out = {}
    for role, value in config.get("agents", {}).items():
        if not isinstance(value, dict) or not isinstance(value.get("config_file"), str): continue
        rel = value["config_file"]
        path = (root / ".codex" / rel).resolve()
        if path.is_relative_to(root.resolve()) and path.is_file(): out[role] = path.relative_to(root.resolve()).as_posix()
    return out

def instruction_hashes(sources: Any, workspace: Path, codex_home: Path | None = None) -> list[dict[str,str]]:
    result=[]
    rows = list(sources) if isinstance(sources, list) else []
    for candidate in (workspace / "AGENTS.md", (codex_home / "AGENTS.md") if codex_home else None):
        if candidate and candidate.is_file(): rows.append(str(candidate))
    seen: set[tuple[str,str]] = set()
    for item in rows:
        if isinstance(item, str): raw=item
        elif isinstance(item, dict): raw=item.get("path") or item.get("file")
        else: continue
        if not isinstance(raw,str): continue
        p=Path(raw)
        try:
            resolved=p.resolve(strict=True)
            label="workspace" if resolved.is_relative_to(workspace.resolve()) else ("project" if resolved.is_relative_to(ROOT.resolve()) else "user")
            row=(label,sha256(resolved.read_bytes()))
            if row not in seen: result.append({"scope":label,"sha256":row[1]}); seen.add(row)
        except (OSError, RuntimeError): continue
    return result

def isolated_codex_home(allowed_mcp: set[str]) -> Path:
    """Build a process-local CODEX_HOME with MCP servers disabled by default."""
    original = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    source_config = original / "config.toml"
    try:
        source_text = source_config.read_text(encoding="utf-8") if source_config.exists() else ""
    except OSError as exc:
        raise CaptureError("user Codex config cannot be read") from exc
    filtered = strip_mcp_tables(source_text, allowed_mcp)
    home = Path(tempfile.mkdtemp(prefix="codex-app-server-home-"))
    home.chmod(0o700)
    if filtered:
        target = home / "config.toml"
        target.write_text(filtered, encoding="utf-8")
        target.chmod(0o600)
    # Preserve identity and instruction sources without copying secret-bearing files.
    for name in ("auth.json", "AGENTS.md", "hooks.json", "rules", "skills"):
        src = original / name
        if src.exists() and not (home / name).exists():
            (home / name).symlink_to(src, target_is_directory=src.is_dir())
    return home

def build_app_server_env(codex_home: Path) -> dict[str, str]:
    """Return provider/runtime necessities only; exclude inherited API credentials."""
    allowed = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "XDG_CACHE_HOME")
    result = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    result["CODEX_HOME"] = str(codex_home.resolve())
    return result

def build_parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command", required=True)
    prep=sub.add_parser("prepare-workspace"); prep.add_argument("--source-root",type=Path,required=True); prep.add_argument("--case-id",required=True); prep.add_argument("--allow",action="append",required=True); prep.add_argument("--evidence-dir",type=Path,required=True)
    cap=sub.add_parser("capture"); cap.add_argument("--workspace",type=Path,required=True); cap.add_argument("--manifest",type=Path,required=True); cap.add_argument("--output",type=Path,required=True); cap.add_argument("--run",action="store_true"); cap.add_argument("--allow-model-usage",action="store_true"); cap.add_argument("--task-file",type=Path); cap.add_argument("--timeout",type=int,default=120); cap.add_argument("--max-child-agents",type=int,default=1); cap.add_argument("--mcp-allow",action="append",default=[])
    return p

def main(argv: list[str] | None = None) -> int:
    args=build_parser().parse_args(argv)
    runtime_workspace: Path | None = None
    prepared_workspace: Path | None = None
    codex_home: Path | None = None
    manifest: dict[str, Any] | None = None
    try:
        if args.command == "prepare-workspace":
            workspace, manifest=prepare_workspace(args.source_root,args.case_id,args.allow,args.evidence_dir)
            print(json.dumps({"workspace":str(workspace),"manifest":manifest},sort_keys=True)); return 0
        if args.timeout<1 or args.timeout>MAX_TIMEOUT or args.max_child_agents<0 or args.max_child_agents>3: raise CaptureError("timeout or child agent limit is outside supported bounds")
        if args.run and not args.allow_model_usage: raise CaptureError("live model usage requires --allow-model-usage")
        if args.allow_model_usage and not args.run: raise CaptureError("--allow-model-usage requires --run")
        if args.run and (not args.task_file or not args.task_file.is_file()): raise CaptureError("explicit task file is required for a live turn")
        manifest=json.loads(args.manifest.read_text(encoding="utf-8")); verify_workspace(args.workspace,manifest)
        if manifest.get("generated_by") != "appserver_capture": raise CaptureError("workspace manifest was not generated by this adapter")
        recorded_root=manifest.get("workspace",{}).get("root") if isinstance(manifest.get("workspace"),dict) else None
        if not isinstance(recorded_root,str) or Path(recorded_root).resolve()!=args.workspace.resolve(): raise CaptureError("workspace root does not match its manifest")
        prepared_workspace=args.workspace.resolve()
        if manifest.get("run_id") is None: raise CaptureError("blinding manifest run ID is missing")
        manifest["manifest_path"] = str(args.manifest.resolve())
        if args.output.parent.resolve() != args.manifest.parent.resolve():
            raise CaptureError("capture output and blinding manifest must share an evidence directory")
        runtime_workspace,manifest=materialize_runtime_workspace(args.workspace,manifest,args.manifest.parent,set(args.mcp_allow))
        config_path=runtime_workspace/".codex/config.toml"
        if not config_path.is_file(): raise CaptureError("isolated workspace must include its project Codex config")
        if tomllib is None: raise CaptureError("TOML parser is required (Python 3.11+ or tomli)")
        project_config=tomllib.loads(config_path.read_text(encoding="utf-8"))
        before=profile_hashes(runtime_workspace,project_config)
        codex_home=isolated_codex_home(set(args.mcp_allow))
        codex_executable=shutil.which("codex")
        if not codex_executable: raise CaptureError("Codex CLI executable is unavailable")
        proc=subprocess.Popen([codex_executable,"app-server","--stdio"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=runtime_workspace,env=build_app_server_env(codex_home))
        client=JsonRpcClient(proc,timeout=min(args.timeout,30))
        start=time.monotonic()
        try:
            client.request("initialize",{"clientInfo":{"name":"codex-app-server-capture","version":"1"}})
            client.notify("initialized",{})
            resolved=client.request("config/read",{})
            config=resolved.get("config") if isinstance(resolved.get("config"),dict) else resolved
            client.store.model=config.get("model") if isinstance(config.get("model"),str) else None
            client.store.version=resolved.get("version") if isinstance(resolved.get("version"),str) else None
            roles=config.get("agents",{}) if isinstance(config,dict) else {}
            if not isinstance(roles,dict) or not roles: raise CaptureError("resolved project agent roles are missing")
            manifest["resolved_role_config"] = profile_paths(runtime_workspace, config)
            if args.run:
                # Explicit live-run path always ephemeral/read-only and bounded fanout.
                started=client.request("thread/start",{"ephemeral":True,"sandbox":"read-only","cwd":str(runtime_workspace)})
                thread=started.get("thread")
                tid=thread.get("id") if isinstance(thread,dict) else None
                if not isinstance(tid,str): raise CaptureError("app-server did not return a thread identity")
                client.store.consume({"method":"thread/started","params":{"thread":thread}})
                client.request("turn/start",{"threadId":tid,"input":[{"type":"text","text":args.task_file.read_text(encoding="utf-8")}],"effort":"low"})
                deadline=start+args.timeout
                while time.monotonic()<deadline:
                    client.drain(min(.2,max(0,deadline-time.monotonic())))
                    if client.store.status in {"failed", "completed"}: break
                    if client.store.spawn_calls>args.max_child_agents: proc.send_signal(signal.SIGINT); raise CaptureError("observed child agent limit exceeded")
                else: proc.send_signal(signal.SIGINT); client.store.status="timed_out"
            else:
                # The default path stops after config/read. It never starts a thread or turn.
                pass
            duration=time.monotonic()-start
            after=profile_hashes(runtime_workspace,project_config)
            sources=instruction_hashes(resolved.get("instructionSources"),runtime_workspace,codex_home)
            event_digest=client.store.capture_event_sha256(manifest["run_id"],duration,before,after,sources)
            manifest=finalize_workspace_manifest(args.manifest,manifest,event_digest)
            manifest["manifest_path"] = str(args.manifest.resolve())
            manifest["capture_event_sha256"] = event_digest
            record=client.store.record(manifest["run_id"],duration,manifest,before,after,sources)
            # Log only sanitized structure. Manifest itself is separately hashed and contains no absolute paths.
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n",encoding="utf-8"); args.output.chmod(0o600)
            print(json.dumps({"status":record["status"],"output":str(args.output),"run_id":record["run_id"],"cost":"N/A"},sort_keys=True))
            return 0 if record["status"] in {"completed","PENDING"} else 1
        finally:
            if proc.poll() is None: proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            client.close()
    except (CaptureError,OSError,ValueError,KeyError,TimeoutError) as exc:
        print(json.dumps({"error":str(exc)},sort_keys=True),file=sys.stderr); return 2
    finally:
        if codex_home is not None: shutil.rmtree(codex_home, ignore_errors=True)
        if hasattr(args, "manifest"):
            expected_temp_parent=args.manifest.parent.resolve().parent
            cleanup_id=manifest.get("run_id") if isinstance(manifest,dict) else ""
            if runtime_workspace is not None: cleanup_owned_workspace(runtime_workspace, "codex-runtime-case-", expected_temp_parent, cleanup_id)
            if prepared_workspace is not None: cleanup_owned_workspace(prepared_workspace, "codex-case-", expected_temp_parent, cleanup_id)

if __name__=="__main__": raise SystemExit(main())

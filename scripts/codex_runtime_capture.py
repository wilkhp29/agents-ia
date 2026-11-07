#!/usr/bin/env python3
"""Run one Codex CLI task and persist only minimized runtime metrics.

Prompt and JSONL events are processed in memory. The only durable output is a
small allowlisted metrics record under logs/runtime/. Agent response text is
returned to the caller after successful parsing and is never put in the log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".codex/config.toml"
METRICS_PATH = ROOT / "logs/runtime/codex_runs.jsonl"
MAX_PROMPT_BYTES = 256 * 1024
MAX_EVENT_BYTES = 1024 * 1024
MAX_FINAL_BYTES = 256 * 1024
MAX_EVENTS = 100_000
DEFAULT_TIMEOUT_SECONDS = 900
MAX_TIMEOUT_SECONDS = 1800
MAX_COUNTER = 10**12
TASK_SIZES = {"small", "medium", "large", "unknown"}
ROLE_NAMES = {
    "intake-normalizer", "product-manager", "software-architect",
    "software-engineer", "code-reviewer", "product-qa",
    "governance-specialist",
    "egm-comprehension", "egm-zoom-out", "egm-design", "egm-structural",
    "egm-style", "egm-implementation-readiness", "egm-codebase-details",
}
PROJECT_ROLES = ROLE_NAMES
NON_ROLE_AGENT_KEYS = {
    "enabled", "max_concurrent_threads_per_session", "max_depth",
    "default_subagent_model", "default_subagent_reasoning_effort",
    "interrupt_message", "job_max_runtime_seconds",
}
VERSION_RE = re.compile(r"^codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
USAGE_KEYS = {
    "input_tokens": "tokens_input",
    "output_tokens": "tokens_output",
    "cached_input_tokens": "cached_tokens_input",
    "reasoning_output_tokens": "reasoning_tokens_output",
}


class CaptureError(ValueError):
    """Sanitized error: messages must never include raw event content."""


@dataclass(frozen=True)
class Capture:
    metric: dict[str, object]
    final_message: str


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_project_roles() -> dict[str, str]:
    try:
        config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CaptureError("project agent configuration is unavailable or invalid") from error
    agents = config.get("agents")
    if not isinstance(agents, dict):
        raise CaptureError("project agent role configuration is missing")
    roles: dict[str, str] = {}
    for name, value in agents.items():
        if name in NON_ROLE_AGENT_KEYS:
            continue
        if name not in ROLE_NAMES or not isinstance(value, dict):
            raise CaptureError("project agent role configuration contains an unsupported role")
        config_file = value.get("config_file")
        expected = f"../agents/{name}.toml"
        if config_file != expected:
            raise CaptureError("project agent role path does not match the versioned profile")
        role_path = (CONFIG.parent / config_file).resolve()
        try:
            role_path.relative_to(ROOT.resolve())
        except ValueError as error:
            raise CaptureError("project agent role path escapes the workspace") from error
        if not role_path.is_file():
            raise CaptureError("a configured project agent profile is missing")
        roles[name] = config_file
    if not roles:
        raise CaptureError("no supported project agent roles are configured")
    return roles


class Accumulator:
    def __init__(self, *, task_size: str, runtime_version: str) -> None:
        if task_size not in TASK_SIZES:
            raise CaptureError("invalid task size")
        if not VERSION_RE.fullmatch(runtime_version):
            raise CaptureError("runtime version is not in the expected form")
        self.task_size = task_size
        self.runtime_version = runtime_version
        self.run_id: str | None = None
        self.started_at: str | None = None
        self.turns = 0
        self.turns_completed = 0
        self.failures = 0
        self.collaboration_tool_calls = 0
        self.agent_spawn_calls = 0
        self.agent_spawn_completed = 0
        self.agent_spawn_failures = 0
        self.agent_dispatches_observed = 0
        self._seen_receiver_hashes: set[str] = set()
        self.unknown_events = 0
        self.token_totals = {value: 0 for value in USAGE_KEYS.values()}
        self.token_seen = {value: True for value in USAGE_KEYS.values()}
        self.final_message = ""
        self.events = 0

    def consume(self, raw: bytes) -> None:
        self.events += 1
        if self.events > MAX_EVENTS:
            raise CaptureError("runtime event count exceeds the configured limit")
        if len(raw) > MAX_EVENT_BYTES:
            raise CaptureError("runtime event exceeds the configured size limit")
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CaptureError("runtime stream contains an invalid event") from error
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise CaptureError("runtime stream contains an unsupported event")
        kind = event["type"]
        if kind == "thread.started":
            thread_id = event.get("thread_id")
            if self.run_id is not None or not isinstance(thread_id, str) or not thread_id or len(thread_id) > 256:
                raise CaptureError("runtime stream has invalid thread identity")
            self.run_id = "run_" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]
            self.started_at = now_utc()
        elif kind == "turn.started":
            self.turns += 1
        elif kind == "turn.completed":
            self.turns_completed += 1
            usage = event.get("usage")
            if usage is None:
                for target in self.token_seen:
                    self.token_seen[target] = False
            elif not isinstance(usage, dict):
                raise CaptureError("runtime usage payload is invalid")
            else:
                for source, target in USAGE_KEYS.items():
                    value = usage.get(source)
                    if value is None:
                        self.token_seen[target] = False
                    elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNTER:
                        raise CaptureError("runtime usage counter is invalid")
                    else:
                        self.token_totals[target] += value
                        if self.token_totals[target] > MAX_COUNTER:
                            raise CaptureError("runtime usage counter exceeds the supported range")
        elif kind == "turn.failed" or kind == "error":
            self.failures += 1
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                raise CaptureError("runtime item event is invalid")
            item_type = item.get("type")
            tool_name = item.get("tool")
            namespace = item.get("namespace")
            call_name = item.get("name") or item.get("tool_name")
            is_collaboration_item = item_type == "collab_tool_call"
            is_collaboration_event = is_collaboration_item or namespace in {"collaboration", "multi_agent_v1"}
            is_spawn = (
                is_collaboration_item and tool_name == "spawn_agent"
            ) or (
                call_name == "spawn_agent" and namespace in {"collaboration", "multi_agent_v1"}
            )
            if kind == "item.started" and is_collaboration_event:
                self.collaboration_tool_calls += 1
            if kind == "item.started" and is_spawn:
                self.agent_spawn_calls += 1
            if kind == "item.completed" and is_spawn:
                status = item.get("status")
                if status == "completed":
                    self.agent_spawn_completed += 1
                elif status == "failed":
                    self.agent_spawn_failures += 1
            if kind == "item.completed" and is_collaboration_event and item.get("status") == "completed":
                receivers = item.get("receiver_thread_ids")
                if isinstance(receivers, list):
                    for receiver in receivers:
                        if not isinstance(receiver, str) or not receiver or len(receiver) > 256:
                            continue
                        digest = hashlib.sha256(receiver.encode("utf-8")).hexdigest()
                        if digest not in self._seen_receiver_hashes:
                            self._seen_receiver_hashes.add(digest)
                            self.agent_dispatches_observed += 1
            if kind == "item.completed" and item.get("type") == "agent_message":
                message = item.get("text")
                if not isinstance(message, str) or len(message.encode("utf-8")) > MAX_FINAL_BYTES:
                    raise CaptureError("runtime response is invalid or too large")
                self.final_message = message
        else:
            # Event schemas evolve. Discard unknown payloads without echoing or storing them.
            self.unknown_events += 1

    def finish(self, *, duration_seconds: float, process_status: int, timed_out: bool = False, allow_incomplete: bool = False) -> Capture:
        if self.run_id is None or self.started_at is None:
            raise CaptureError("runtime stream did not identify a session")
        if self.turns_completed < 1 and not allow_incomplete and not self.failures:
            raise CaptureError("runtime stream did not complete a turn")
        if not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise CaptureError("runtime duration is invalid")
        if process_status != 0 and not timed_out and not self.failures:
            self.failures += 1
        status = "timed_out" if timed_out else ("failed" if self.failures else "completed")
        if self.turns_completed == 0:
            for target in self.token_seen:
                self.token_seen[target] = False
        metric: dict[str, object] = {
            "schema_version": 2,
            "source": "codex_cli_jsonl",
            "run_id": self.run_id,
            "task_size": self.task_size,
            "runtime_version": self.runtime_version,
            "status": status,
            "started_at": self.started_at,
            "captured_at": now_utc(),
            "duration_seconds": round(duration_seconds, 3),
            "turns": self.turns,
            "turns_completed": self.turns_completed,
            "failures": self.failures,
            "collaboration_tool_calls": self.collaboration_tool_calls,
            "agent_spawn_calls": self.agent_spawn_calls,
            "agent_spawn_completed": self.agent_spawn_completed,
            "agent_spawn_failures": self.agent_spawn_failures,
            "agent_dispatches_observed": self.agent_dispatches_observed,
            "unknown_events": self.unknown_events,
            "profile_identity_verified": False,
        }
        for target in USAGE_KEYS.values():
            metric[target] = self.token_totals[target] if self.token_seen[target] else None
        return Capture(metric=metric, final_message=self.final_message)


def parse_stream(lines: Iterable[str | bytes], *, task_size: str, runtime_version: str, duration_seconds: float) -> Capture:
    accumulator = Accumulator(task_size=task_size, runtime_version=runtime_version)
    for line in lines:
        raw = line.encode("utf-8") if isinstance(line, str) else line
        if not raw:
            continue
        accumulator.consume(raw)
    return accumulator.finish(duration_seconds=duration_seconds, process_status=0)


def build_exec_args(roles: dict[str, str], *, executable: str, sandbox: str) -> list[str]:
    """Register project roles as CLI overrides for reliable spawn resolution.

    Codex CLI versions have had a config-loading issue where roles declared
    only in project `.codex/config.toml` were not visible to `spawn_agent`.
    Re-registering the already validated roles as CLI `-c` overrides keeps the
    runtime self-contained and avoids editing user-global Codex configuration.
    """
    try:
        config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CaptureError("project agent configuration is unavailable or invalid") from error
    agent_config = config.get("agents")
    if not isinstance(agent_config, dict):
        raise CaptureError("project agent role configuration is missing")

    args = [executable, "exec", "--ignore-user-config", "--enable", "multi_agent"]
    for name, relative_path in sorted(roles.items()):
        role = agent_config.get(name)
        if not isinstance(role, dict) or role.get("config_file") != relative_path:
            raise CaptureError("project agent role configuration changed during runtime setup")
        description = role.get("description")
        if not isinstance(description, str) or not description.strip():
            raise CaptureError("project agent role description is missing")
        absolute_path = str((CONFIG.parent / relative_path).resolve())
        args.extend(("-c", f"agents.{name}.description={json.dumps(description)}"))
        args.extend(("-c", f"agents.{name}.config_file={json.dumps(absolute_path)}"))
    args.extend(("--json", "--ephemeral", "--sandbox", sandbox, "-"))
    return args


def codex_version(executable: str) -> str:
    try:
        result = subprocess.run([executable, "--version"], cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CaptureError("Codex CLI version could not be observed") from error
    version = result.stdout.strip()
    if result.returncode != 0 or not VERSION_RE.fullmatch(version):
        raise CaptureError("Codex CLI version is unsupported or not observable")
    return version


def append_metric(metric: dict[str, object]) -> None:
    directory = METRICS_PATH.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = ROOT.resolve()
    resolved_dir = directory.resolve()
    try:
        resolved_dir.relative_to(root)
    except ValueError as error:
        raise CaptureError("runtime metrics destination escapes the workspace") from error
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(METRICS_PATH, flags, 0o600)
    except OSError as error:
        raise CaptureError("runtime metrics destination could not be opened safely") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise CaptureError("runtime metrics destination is not a regular file")
        os.fchmod(descriptor, 0o600)
        data = (json.dumps(metric, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    except OSError as error:
        raise CaptureError("runtime metrics record could not be written safely") from error
    finally:
        os.close(descriptor)


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if process.poll() is None:
            process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait()


def run_prompt(prompt: bytes, *, task_size: str, sandbox: str = "read-only", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> Capture:
    if sandbox not in {"read-only", "workspace-write"}:
        raise CaptureError("unsupported sandbox mode")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise CaptureError("timeout must be between 1 and the configured maximum")
    executable = shutil.which("codex")
    if not executable:
        raise CaptureError("Codex CLI is not available on PATH")
    roles = load_project_roles()
    if not roles:
        raise CaptureError("no project agent roles are configured")
    version = codex_version(executable)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            build_exec_args(roles, executable=executable, sandbox=sandbox), cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise CaptureError("Codex CLI could not be started") from error
    assert process.stdin is not None and process.stdout is not None
    try:
        accumulator = Accumulator(task_size=task_size, runtime_version=version)
        deadline = started + timeout_seconds
        buffer = bytearray()
        timed_out = False
        input_offset = 0
        input_closed = False
        stdout_closed = False
        os.set_blocking(process.stdin.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    terminate_process_group(process)
                    break
                readable = selector.select(min(remaining, 0.5))
                if not readable:
                    if process.poll() is not None and stdout_closed:
                        break
                    continue
                for key, _mask in readable:
                    if key.data == "stdin":
                        chunk = prompt[input_offset : input_offset + 64 * 1024]
                        try:
                            written = os.write(process.stdin.fileno(), chunk)
                        except BrokenPipeError as error:
                            raise CaptureError("Codex CLI stopped before accepting the prompt") from error
                        input_offset += written
                        if input_offset >= len(prompt):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                            input_closed = True
                    else:
                        chunk = os.read(process.stdout.fileno(), 64 * 1024)
                        if not chunk:
                            selector.unregister(process.stdout)
                            stdout_closed = True
                            continue
                        buffer.extend(chunk)
                        while True:
                            newline = buffer.find(b"\n")
                            if newline < 0:
                                break
                            line = bytes(buffer[:newline])
                            del buffer[: newline + 1]
                            accumulator.consume(line)
                        if len(buffer) > MAX_EVENT_BYTES:
                            terminate_process_group(process)
                            raise CaptureError("runtime event exceeds the configured size limit")
                if stdout_closed and input_closed and process.poll() is not None:
                    break
        if buffer and not timed_out:
            terminate_process_group(process)
            raise CaptureError("runtime stream ended with an incomplete event")
        # On timeout, discard a partial JSONL fragment. It is not a validated
        # event and must not prevent persistence of observed, minimized metrics.
        buffer.clear()
        return_code = process.wait()
        duration = time.monotonic() - started
        capture = accumulator.finish(duration_seconds=duration, process_status=return_code,
                                     timed_out=timed_out, allow_incomplete=timed_out)
        append_metric(capture.metric)
        if capture.metric["status"] != "completed":
            raise CaptureError("Codex CLI task failed or timed out; minimized metrics were saved")
        return capture
    except CaptureError:
        if process.poll() is None:
            terminate_process_group(process)
        else:
            process.wait()
        raise
    except (OSError, UnicodeError) as error:
        terminate_process_group(process)
        raise CaptureError("Codex CLI stream could not be processed safely") from error
    finally:
        process.stdout.close()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-size", choices=sorted(TASK_SIZES), default="unknown")
    parser.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help=f"terminate the Codex process tree after this many seconds (max {MAX_TIMEOUT_SECONDS})")
    args = parser.parse_args(argv)
    try:
        prompt = sys.stdin.buffer.read(MAX_PROMPT_BYTES + 1)
        if len(prompt) > MAX_PROMPT_BYTES:
            raise CaptureError("prompt exceeds the configured size limit")
        if not prompt.strip():
            raise CaptureError("prompt is empty")
        capture = run_prompt(prompt, task_size=args.task_size, sandbox=args.sandbox, timeout_seconds=args.timeout_seconds)
        # The final answer is returned to this invocation's caller, but never persisted.
        if capture.final_message:
            sys.stdout.write(capture.final_message)
            if not capture.final_message.endswith("\n"):
                sys.stdout.write("\n")
        else:
            raise CaptureError("runtime completed without a final response")
        print(f"[codex metrics saved: {METRICS_PATH.relative_to(ROOT)}; profile identity verified: false]", file=sys.stderr)
        return 0
    except CaptureError as error:
        print(f"codex runtime capture failed: {error}", file=sys.stderr)
        return 2


def main_guard() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    main_guard()

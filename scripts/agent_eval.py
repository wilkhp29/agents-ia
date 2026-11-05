#!/usr/bin/env python3
"""Prepare and validate evidence records for the agent workflow eval suite.

This tool does not invoke an LLM or claim that a Codex TOML profile ran. It
creates a pinned, repeatable record shell and validates human/runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import json
import os
import re
import subprocess
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "docs/evaluations/agent-workflow-v1.json"
STATUSES = {"NOT RUN", "PENDING", "PASS", "FAIL", "BLOCKED"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False
    )
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def git_bytes(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed ({result.returncode}): {message}")
    return result.stdout


def load_suite() -> dict[str, Any]:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    ids = [item.get("id") for item in suite.get("cases", [])]
    if ids != [f"E{i}" for i in range(1, 9)]:
        raise ValueError("suite must contain E1 through E8 once, in order")
    return suite


def profile_dir(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser().resolve() / "agents"
    return ROOT / "agents"


def fingerprints(directory: Path, suite: dict[str, Any]) -> dict[str, str]:
    names = sorted({name for case in suite["cases"] for name in case["profiles"]})
    result: dict[str, str] = {}
    for name in names:
        path = directory / f"{name}.toml"
        result[name] = sha256(path.read_bytes()) if path.is_file() else "MISSING"
    return result


def verify_evidence_reference(record_dir: Path, evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    relative = evidence.get("uri")
    expected = evidence.get("sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return False
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    candidate = (record_dir / relative).resolve()
    try:
        candidate.relative_to(record_dir.resolve())
    except ValueError:
        return False
    return candidate.is_file() and sha256(candidate.read_bytes()) == expected


def valid_sha(value: Any, length: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(rf"[0-9a-f]{{{length}}}", value))


def nonnegative_number(value: Any) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value >= 0
    )


def prepare(args: argparse.Namespace) -> Path:
    suite = load_suite()
    selected = set(args.case or [case["id"] for case in suite["cases"]])
    unknown = selected - {case["id"] for case in suite["cases"]}
    if unknown:
        raise ValueError(f"unknown case(s): {', '.join(sorted(unknown))}")
    chosen = [case for case in suite["cases"] if case["id"] in selected]
    commit = git_output("rev-parse", "HEAD")
    status_bytes = git_bytes("status", "--porcelain=v1", "-z")
    dirty = bool(status_bytes)
    if dirty and not args.allow_dirty:
        raise ValueError("worktree is dirty; prepare from a clean, committed snapshot (or use --allow-dirty only for local harness validation)")
    diff_hash = sha256(git_bytes("diff", "--binary", "HEAD"))
    profiles = fingerprints(profile_dir(args.profiles), suite)
    run = {
        "schema_version": 1,
        "suite": suite["suite"],
        "suite_sha256": sha256(SUITE.read_bytes()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": str(ROOT),
        "git": {"branch": git_output("branch", "--show-current"), "commit": commit, "dirty": dirty,
                "snapshot_reproducible": not dirty, "status_sha256": sha256(status_bytes),
                "tracked_diff_sha256": diff_hash},
        "runtime": {"name": "PENDING", "version": "PENDING", "profile_load_identity_verified": False},
        "profiles": {"source_directory": str(profile_dir(args.profiles)), "sha256": profiles},
        "repetitions_requested": args.runs,
        "selected_case_ids": [case["id"] for case in chosen],
        "safety": {"isolated_fixture_or_worktree": False, "external_tools_mocked_fail_closed": False, "operator_note": "Set true only after recording the actual isolated setup and blocked external tools."},
        "cases": [
            {
                "id": case["id"], "title": case["title"], "risk": case["risk"],
                "required_profiles": case["profiles"], "source": case["source"],
                "trials": [
                    {"attempt": i + 1, "status": "NOT RUN", "profile_load_identity_verified": False,
                     "observed_profiles": {
                         name: {"identity_verified": False, "sha256": None}
                         for name in case["profiles"]
                     },
                     "evidence": [], "deterministic_judges": [], "duration_seconds": None,
                     "tokens": None, "cost": None, "findings": []}
                    for i in range(args.runs)
                ]
            }
            for case in chosen
        ],
        "summary": {"status": "PENDING", "reviewer": None, "hard_fail": False, "notes": []},
    }
    output = Path(args.output) if args.output else ROOT / "docs/evaluations/runs" / f"{datetime.now().strftime('%Y-%m-%d')}-{commit[:8]}-{datetime.now().strftime('%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared run record: {output}")
    print(f"Pinned package commit: {commit}")
    print(f"Profile fingerprints captured: {sum(value != 'MISSING' for value in profiles.values())}/{len(profiles)}")
    print("Runtime execution: NOT RUN (this script does not invoke Codex profiles)")
    return output


def validate_record(path: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("run record must be a JSON object")
    suite = load_suite()
    if record.get("suite") != suite["suite"]:
        raise ValueError("record suite does not match current suite")
    if not valid_sha(record.get("suite_sha256"), 64) or record["suite_sha256"] != sha256(SUITE.read_bytes()):
        raise ValueError("record suite hash is stale; prepare a new run for the current suite")
    git_info = record.get("git")
    profile_info = record.get("profiles")
    if not isinstance(git_info, dict) or not valid_sha(git_info.get("commit"), 40):
        raise ValueError("record must pin a 40-character Git commit SHA")
    if not isinstance(git_info.get("branch"), str) or not isinstance(git_info.get("dirty"), bool):
        raise ValueError("record must include branch and boolean dirty state")
    if not valid_sha(git_info.get("status_sha256"), 64) or not valid_sha(git_info.get("tracked_diff_sha256"), 64):
        raise ValueError("record must fingerprint Git status and tracked diff")
    if not isinstance(git_info.get("snapshot_reproducible"), bool):
        raise ValueError("record must state whether the snapshot is reproducible")
    if git_info["snapshot_reproducible"] == git_info["dirty"]:
        raise ValueError("snapshot_reproducible must be the inverse of dirty")
    if not isinstance(profile_info, dict) or not isinstance(profile_info.get("sha256"), dict):
        raise ValueError("record must pin package commit and profile fingerprints")
    for name, digest in profile_info["sha256"].items():
        if not isinstance(name, str) or (digest != "MISSING" and not valid_sha(digest, 64)):
            raise ValueError("profile fingerprints must be SHA-256 hex strings or MISSING")
    repetitions = record.get("repetitions_requested")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("repetitions_requested must be positive")
    selected_list = record.get("selected_case_ids")
    if not isinstance(selected_list, list) or any(not isinstance(value, str) for value in selected_list):
        raise ValueError("selected_case_ids must be a list of case IDs")
    case_ids: list[str] = []
    hard_fail = False
    critical_finding_case: str | None = None
    pending = False
    failed = False
    cases = record.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be a JSON object")
        case_id = case.get("id")
        case_ids.append(case_id)
        expected_case = next((item for item in suite["cases"] if item["id"] == case_id), None)
        if expected_case is None:
            raise ValueError(f"unknown case in record: {case_id}")
        for field in ("title", "risk", "source"):
            if case.get(field) != expected_case[field]:
                raise ValueError(f"{case_id}: {field} differs from the versioned suite")
        if case.get("required_profiles") != expected_case["profiles"]:
            raise ValueError(f"{case_id}: required_profiles differ from the versioned suite")
        trials = case.get("trials")
        if not isinstance(trials, list) or len(trials) != repetitions:
            raise ValueError(f"{case['id']}: trial count does not match requested repetitions")
        for index, trial in enumerate(trials):
            if not isinstance(trial, dict):
                raise ValueError(f"{case['id']}: each trial must be a JSON object")
            attempt = trial.get("attempt")
            if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt != index + 1:
                raise ValueError(f"{case['id']}: attempts must be numbered sequentially from 1")
            status = trial.get("status")
            if status not in STATUSES:
                raise ValueError(f"{case['id']}: invalid trial status {status!r}")
            if not isinstance(trial.get("profile_load_identity_verified"), bool):
                raise ValueError(f"{case['id']}: profile_load_identity_verified must be boolean")
            observed_profiles = trial.get("observed_profiles")
            required_profiles = case["required_profiles"]
            if not isinstance(observed_profiles, dict) or set(observed_profiles) != set(required_profiles):
                raise ValueError(f"{case['id']}: observed_profiles must contain every required profile exactly once")
            verified_profiles: list[str] = []
            for profile_name in required_profiles:
                observation = observed_profiles[profile_name]
                if not isinstance(observation, dict) or not isinstance(observation.get("identity_verified"), bool):
                    raise ValueError(f"{case['id']}: {profile_name} identity observation is invalid")
                loaded_sha = observation.get("sha256")
                manifest_sha = profile_info["sha256"].get(profile_name)
                if observation["identity_verified"]:
                    if not valid_sha(loaded_sha, 64) or manifest_sha in {None, "MISSING"} or loaded_sha != manifest_sha:
                        raise ValueError(f"{case['id']}: {profile_name} loaded fingerprint does not match profiles.sha256")
                    verified_profiles.append(profile_name)
                elif loaded_sha is not None:
                    raise ValueError(f"{case['id']}: unverified {profile_name} must not claim a loaded fingerprint")
            all_required_profiles_verified = len(verified_profiles) == len(required_profiles)
            if trial["profile_load_identity_verified"] != all_required_profiles_verified:
                raise ValueError(f"{case['id']}: aggregate profile identity flag must match per-profile observations")
            for field in ("duration_seconds", "tokens", "cost"):
                if not nonnegative_number(trial.get(field)):
                    raise ValueError(f"{case['id']}: {field} must be a nonnegative number or null")
            if not isinstance(trial.get("evidence"), list) or not isinstance(trial.get("deterministic_judges"), list):
                raise ValueError(f"{case['id']}: evidence and deterministic_judges must be lists")
            if not isinstance(trial.get("findings"), list):
                raise ValueError(f"{case['id']}: findings must be a list")
            trial_hard_fail = False
            for finding in trial["findings"]:
                if not isinstance(finding, dict):
                    raise ValueError(f"{case['id']}: each finding must be an object")
                severity = finding.get("severity")
                if not isinstance(severity, str):
                    raise ValueError(f"{case['id']}: each finding requires a severity P0–P3")
                severity = severity.strip().upper()
                if severity not in {"P0", "P1", "P2", "P3"}:
                    raise ValueError(f"{case['id']}: invalid finding severity {severity!r}; expected P0–P3")
                if not isinstance(finding.get("description"), str) or not finding["description"].strip():
                    raise ValueError(f"{case['id']}: each finding requires a non-empty description")
                if severity in {"P0", "P1"}:
                    trial_hard_fail = True
                    critical_finding_case = case["id"]
            if trial_hard_fail:
                hard_fail = True
                if status == "PASS":
                    raise ValueError(f"{case['id']}: P0/P1 finding cannot be marked PASS, regardless of optional hard_fail flags")
            if status == "PASS":
                if not all_required_profiles_verified:
                    raise ValueError(f"{case['id']}: PASS requires verified identity and matching SHA-256 for every required profile")
                evidence = trial.get("evidence")
                judges = trial.get("deterministic_judges")
                if not isinstance(evidence, list) or not evidence or any(
                    not verify_evidence_reference(path.resolve().parent, item)
                    for item in evidence
                ):
                    raise ValueError(f"{case['id']}: PASS requires existing evidence files within the run directory with matching SHA-256")
                if not isinstance(judges, list) or not judges or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("name"), str) or not item["name"]
                    or not isinstance(item.get("command"), str) or not item["command"]
                    or not isinstance(item.get("exit_code"), int) or isinstance(item["exit_code"], bool)
                    or item["exit_code"] != 0
                    or not verify_evidence_reference(path.resolve().parent, item.get("evidence"))
                    for item in judges
                ):
                    raise ValueError(f"{case['id']}: PASS requires a successful deterministic judge with verifiable local evidence")
            if status in {"NOT RUN", "PENDING", "BLOCKED"}:
                pending = True
            if status == "FAIL":
                failed = True
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    expected = {item["id"] for item in suite["cases"]}
    selected = set(selected_list)
    if not selected or not selected <= expected or set(case_ids) != selected:
        raise ValueError(f"record case IDs must match its selected_case_ids; present={sorted(case_ids)}")
    summary = record.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("notes"), list):
        raise ValueError("summary must be an object with notes list")
    summary_status = summary.get("status")
    runtime = record.get("runtime")
    safety = record.get("safety")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("profile_load_identity_verified"), bool):
        raise ValueError("runtime must include a boolean profile_load_identity_verified")
    if not isinstance(safety, dict) or not isinstance(safety.get("isolated_fixture_or_worktree"), bool) or not isinstance(safety.get("external_tools_mocked_fail_closed"), bool):
        raise ValueError("safety must record isolation and fail-closed mock booleans")
    if not isinstance(summary.get("hard_fail"), bool):
        raise ValueError("summary hard_fail must be boolean")
    if hard_fail and not summary["hard_fail"]:
        raise ValueError(f"summary must retain P0/P1 hard-fail from findings (case {critical_finding_case})")
    if summary_status not in STATUSES:
        raise ValueError(f"invalid summary status: {summary_status!r}")
    if hard_fail and summary_status != "BLOCKED":
        raise ValueError("a P0/P1 hard fail must keep the run BLOCKED")
    if summary_status == "PASS" and (pending or failed or hard_fail):
        raise ValueError("summary cannot PASS with pending, blocked, or failed trials")
    if summary_status == "PASS" and summary["hard_fail"]:
        raise ValueError("summary cannot PASS when hard_fail is true")
    if summary_status == "PASS" and any(
        trial.get("status") != "PASS"
        for case in record["cases"] for trial in case["trials"]
    ):
        raise ValueError("summary PASS requires every selected trial to PASS")
    if summary_status == "PASS":
        if runtime.get("name") in {None, "", "PENDING"} or runtime.get("version") in {None, "", "PENDING"}:
            raise ValueError("summary PASS requires observed runtime name and version")
        if not runtime.get("profile_load_identity_verified"):
            raise ValueError("summary PASS requires verified runtime profile load identity")
        if not record.get("safety", {}).get("isolated_fixture_or_worktree"):
            raise ValueError("summary PASS requires a recorded isolated fixture or worktree")
        if not record.get("safety", {}).get("external_tools_mocked_fail_closed"):
            raise ValueError("summary PASS requires fail-closed external tool mocks")
        if record.get("git", {}).get("dirty") or not record.get("git", {}).get("snapshot_reproducible"):
            raise ValueError("summary PASS requires a clean, reproducible worktree snapshot")
        if any(value == "MISSING" for value in record["profiles"]["sha256"].values()):
            raise ValueError("summary PASS cannot include a missing profile fingerprint")
        if not record.get("summary", {}).get("reviewer"):
            raise ValueError("summary PASS requires a human reviewer")
    print(f"Run record structure: PASS ({len(case_ids)} cases, {record['repetitions_requested']} trial(s) each)")
    print(f"Recorded result: {summary_status}; no agent behavior is inferred by this validator")


def report_record(path: Path) -> None:
    validate_record(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    print("\nCase | Pass rate | Consistency | Median seconds | Median cost")
    for case in record["cases"]:
        trials = case["trials"]
        terminal = [trial["status"] for trial in trials if trial["status"] in {"PASS", "FAIL"}]
        rate = (
            f"{terminal.count('PASS')}/{len(terminal)} ({terminal.count('PASS') / len(terminal):.0%}; {len(terminal)}/{len(trials)} resolved)"
            if terminal else f"N/A (0/{len(trials)} resolved)"
        )
        consistency = (
            f"{max(terminal.count(status) for status in set(terminal))}/{len(terminal)}"
            if terminal and len(terminal) == len(trials) else "N/A"
        )
        durations = [trial["duration_seconds"] for trial in trials if trial["duration_seconds"] is not None]
        costs = [trial["cost"] for trial in trials if trial["cost"] is not None]
        duration = f"{statistics.median(durations):g} s ({len(durations)}/{len(trials)})" if durations else "N/A"
        cost = f"{statistics.median(costs):g} ({len(costs)}/{len(trials)})" if costs else "N/A"
        print(f"{case['id']} | {rate} | {consistency} | {duration} | {cost}")
    print("N/A means runtime telemetry was not recorded; no cost or duration was estimated.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="create a pinned PENDING run record")
    prepare_parser.add_argument("--case", action="append", help="case ID; repeat to select multiple")
    prepare_parser.add_argument("--runs", type=int, default=3, help="trials requested per case (default: 3)")
    prepare_parser.add_argument("--profiles", help="directory with TOML profiles; defaults to CODEX_HOME/agents or repo agents/")
    prepare_parser.add_argument("--output", help="output JSON path")
    prepare_parser.add_argument("--allow-dirty", action="store_true", help="development-only: prepare a non-reproducible PENDING record; such a run can never PASS")
    validate_parser = subparsers.add_parser("validate", help="validate a completed or pending run record")
    validate_parser.add_argument("record", type=Path)
    report_parser = subparsers.add_parser("report", help="summarize pass consistency and observed duration/cost")
    report_parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.runs < 1:
                raise ValueError("--runs must be at least 1")
            prepare(args)
        elif args.command == "validate":
            validate_record(args.record)
        else:
            report_record(args.record)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Agent eval error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
EVALUATIONS_DIR = (ROOT / "docs/evaluations").resolve()
STATUSES = {"NOT RUN", "PENDING", "PASS", "FAIL", "BLOCKED"}
DELIVERY_RUBRIC = EVALUATIONS_DIR / "delivery-size-v1-rubric.json"
SCORING_DIMENSIONS = (
    "scope_refinement",
    "technical_correctness",
    "verification_evidence",
    "safety_gates",
    "delivery_operations",
)
SCORE_VALUES = {0.0, 0.5, 1.0}
MAX_RECORD_BYTES = 8 * 1024 * 1024
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = "2026-11-07"
MINIMUM_HOLDOUT_SCENARIOS = 30
MAX_INTERVAL_HALF_WIDTH = 5.0
SCORE_THRESHOLD = 85.0
ROOT_AGENT_ROLE = "product-lead"


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


def suite_path(value: str | Path | None) -> Path:
    candidate = Path(value).expanduser() if value else SUITE
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(EVALUATIONS_DIR)
    except ValueError as exc:
        raise ValueError("suite must be a file within docs/evaluations") from exc
    if not candidate.is_file() or candidate.suffix != ".json":
        raise ValueError("suite must be an existing JSON file")
    return candidate


def evaluation_json(path: str | Path, *, label: str) -> tuple[Path, dict[str, Any], bytes]:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(EVALUATIONS_DIR)
    except ValueError as exc:
        raise ValueError(f"{label} must be within docs/evaluations") from exc
    if not candidate.is_file() or candidate.suffix != ".json":
        raise ValueError(f"{label} must be an existing JSON file")
    if candidate.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError(f"{label} exceeds the configured size limit")
    raw = candidate.read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return candidate, parsed, raw


def rubric_path(value: str | Path | None = None) -> Path:
    candidate = Path(value).expanduser() if value else DELIVERY_RUBRIC
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(EVALUATIONS_DIR)
    except ValueError as exc:
        raise ValueError("rubric must be within docs/evaluations") from exc
    if not candidate.is_file() or candidate.suffix != ".json":
        raise ValueError("rubric must be an existing JSON file")
    if candidate.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("rubric exceeds the configured size limit")
    return candidate


def load_suite(path: str | Path | None = None) -> dict[str, Any]:
    selected_path = suite_path(path)
    suite = json.loads(selected_path.read_text(encoding="utf-8"))
    cases = suite.get("cases") if isinstance(suite, dict) else None
    if not isinstance(cases, list) or any(not isinstance(item, dict) for item in cases):
        raise ValueError("suite cases must be a list of objects")
    ids = [item.get("id") for item in cases]
    if not ids or any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("suite must contain uniquely identified cases")
    for item in cases:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("title", "risk", "source")):
            raise ValueError("every suite case must define title, risk and source")
        if not isinstance(item.get("profiles"), list) or not item["profiles"] or any(not isinstance(name, str) or not name for name in item["profiles"]):
            raise ValueError(f"{item.get('id', 'case')}: profiles must be a non-empty list of names")
    return suite


def profile_dir(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser().resolve() / "agents"
    return ROOT / "agents"


def profile_source_identifier(value: str | None) -> str:
    directory = profile_dir(value).resolve()
    if directory == (ROOT / "agents").resolve():
        return "workspace-agents"
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and directory == (Path(codex_home).expanduser().resolve() / "agents"):
        return "CODEX_HOME/agents"
    return "custom-directory"


def fingerprints(directory: Path, suite: dict[str, Any]) -> dict[str, str]:
    names = sorted({name for case in suite["cases"] for name in child_profiles(case)})
    result: dict[str, str] = {}
    for name in names:
        path = directory / f"{name}.toml"
        result[name] = sha256(path.read_bytes()) if path.is_file() else "MISSING"
    return result


def child_profiles(case: dict[str, Any]) -> list[str]:
    # Delivery-size trials run from the root coordinator plus child profiles.
    # The root is identified by its instruction-source snapshot, while the
    # legacy workflow suite intentionally measures its product-lead TOML profile.
    if "size" in case:
        return [name for name in case.get("profiles", []) if name != ROOT_AGENT_ROLE]
    return list(case.get("profiles", []))


def file_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes())
    except OSError:
        return "MISSING"


def root_instruction_paths() -> dict[str, Path]:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    return {
        "project_agents": ROOT / "AGENTS.md",
        "global_agents": codex_home / "AGENTS.md",
    }


def root_instruction_snapshot() -> dict[str, Any]:
    source_ids = {
        "project_agents": "project/AGENTS.md",
        "global_agents": "CODEX_HOME/AGENTS.md",
    }
    return {
        "identity_basis": "instruction_source_snapshot",
        "root_role": ROOT_AGENT_ROLE,
        "sources": {
            key: {
                "source_id": source_ids[key],
                "before_sha256": file_sha256(path),
                "after_sha256": None,
            }
            for key, path in root_instruction_paths().items()
        },
    }


def project_profile_config_file(profile_name: str) -> str:
    config_path = ROOT / ".codex/config.toml"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "MISSING"
    in_profile = False
    config_file = None
    section_pattern = re.compile(r"^\[agents\.([A-Za-z0-9_-]+)\]\s*$")
    value_pattern = re.compile(r'^config_file\s*=\s*"([^"\\]+)"\s*(?:#.*)?$')
    for line in lines:
        stripped = line.strip()
        section = section_pattern.fullmatch(stripped)
        if section:
            in_profile = section.group(1) == profile_name
            continue
        if in_profile:
            match = value_pattern.fullmatch(stripped)
            if match:
                config_file = match.group(1)
                break
            if stripped.startswith("["):
                in_profile = False
    if not config_file:
        return "MISSING"
    candidate = (config_path.parent / config_file).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return "MISSING"
    return config_file


def project_profile_config_sha(profile_name: str) -> str:
    config_file = project_profile_config_file(profile_name)
    if config_file == "MISSING":
        return "MISSING"
    path = ((ROOT / ".codex/config.toml").parent / config_file).resolve()
    return file_sha256(path)


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
    return (
        candidate.is_file()
        and candidate.stat().st_size <= MAX_RECORD_BYTES
        and sha256(candidate.read_bytes()) == expected
    )


def validate_materialized_workspace_manifest(
    reference: Any, record_dir: Path, runtime: dict[str, Any]
) -> tuple[bool, str]:
    if not verify_evidence_reference(record_dir, reference):
        return False, "runner-generated materialized workspace evidence is missing or invalid"
    manifest_path = (record_dir / reference["uri"]).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False, "materialized workspace manifest is not valid JSON"
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return False, "materialized workspace manifest schema is unsupported"
    if manifest.get("generated_by") != "appserver_capture":
        return False, "materialized workspace manifest must be emitted by the runtime capture adapter"
    if not isinstance(manifest.get("capture_event_sha256"), str) or not valid_sha(manifest["capture_event_sha256"], 64):
        return False, "materialized workspace manifest lacks runtime event provenance"
    if not isinstance(runtime.get("run_id"), str) or not runtime["run_id"] or manifest.get("run_id") != runtime["run_id"]:
        return False, "materialized workspace manifest is not bound to the observed runtime run"
    workspace = manifest.get("workspace")
    if not isinstance(workspace, dict) or workspace.get("temporary") is not True or workspace.get("git_present") is not False:
        return False, "evaluation must run in a temporary materialized workspace without .git"
    workspace_root = workspace.get("root")
    if not isinstance(workspace_root, str) or not Path(workspace_root).is_absolute():
        return False, "materialized workspace root must be an absolute temporary path"
    resolved_workspace = Path(workspace_root).resolve()
    try:
        resolved_workspace.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        return False, "materialized workspace must be outside the evaluator repository"
    visible_files = manifest.get("visible_files")
    if not isinstance(visible_files, list) or not visible_files:
        return False, "materialized workspace must include a hashed visible-file allowlist"
    seen_paths: set[str] = set()
    for item in visible_files:
        if not isinstance(item, dict):
            return False, "visible-file allowlist contains an invalid entry"
        rel = item.get("path")
        digest = item.get("sha256")
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            return False, "visible-file allowlist paths must be safe relative paths"
        if rel in seen_paths or not valid_sha(digest, 64):
            return False, "visible-file allowlist paths and hashes must be unique and valid"
        parts = set(Path(rel).parts)
        if ".git" in parts or "docs/evaluations" in rel.replace("\\", "/"):
            return False, "evaluator metadata or Git internals are visible to the evaluated agent"
        seen_paths.add(rel)
    excluded = manifest.get("excluded_paths")
    required_exclusions = {
        "docs/evaluations",
        "docs/evaluations/delivery-size-v1.json",
        "docs/evaluations/delivery-size-v1-rubric.json",
    }
    if not isinstance(excluded, list) or not required_exclusions <= set(excluded):
        return False, "manifest does not prove evaluation suite and rubric exclusion"
    return True, "PASS"


def validate_capture_record(
    capture_reference: Any,
    manifest_reference: Any,
    record_dir: Path,
    runtime: dict[str, Any],
    trial: dict[str, Any],
) -> tuple[bool, str]:
    runtime_run_id = trial.get("runtime_run_id")
    if not isinstance(runtime_run_id, str) or not runtime_run_id.strip():
        return False, "trial runtime run ID is missing"
    manifest_runtime = {"run_id": runtime_run_id}
    manifest_ok, manifest_reason = validate_materialized_workspace_manifest(
        manifest_reference, record_dir, manifest_runtime
    )
    if not manifest_ok:
        return False, manifest_reason
    if not verify_evidence_reference(record_dir, capture_reference):
        return False, "runtime capture record is missing or its evidence hash is invalid"
    capture_path = (record_dir / capture_reference["uri"]).resolve()
    try:
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False, "runtime capture record is not valid JSON"
    manifest_path = (record_dir / manifest_reference["uri"]).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False, "materialized workspace manifest is not valid JSON"
    if not isinstance(capture, dict) or capture.get("schema_version") != 1 or capture.get("source") != "codex_app_server":
        return False, "runtime capture record schema/source is unsupported"
    event_digest = capture.get("capture_event_sha256")
    if not valid_sha(event_digest, 64) or event_digest != manifest.get("capture_event_sha256"):
        return False, "capture record event hash does not match the materialized workspace manifest"
    if capture.get("run_id") != runtime_run_id or manifest.get("run_id") != runtime_run_id:
        return False, "capture, manifest, and trial runtime run IDs do not match"
    if capture.get("status") != "completed":
        return False, "runtime capture status is not completed"
    if capture.get("runtime_version") != runtime.get("version"):
        return False, "runtime capture version does not match the observed evaluator runtime"
    if capture.get("usage_status") != "OBSERVED" or trial.get("profile_load_identity_verified") is not True:
        return False, "runtime capture token usage or trial profile identity is unverified"
    if capture.get("agent_identity_status") != "OBSERVED" or capture.get("profile_hashes_match") is not True:
        return False, "runtime capture agent identity or profile hash evidence is unverified"
    profile_before = capture.get("profile_sha256_before")
    profile_after = capture.get("profile_sha256_after")
    if (
        not isinstance(profile_before, dict)
        or not profile_before
        or profile_after != profile_before
        or any(not isinstance(name, str) or not valid_sha(digest, 64) for name, digest in profile_before.items())
    ):
        return False, "runtime capture profile hash maps are missing or changed"
    threads = capture.get("threads")
    if not isinstance(threads, list) or not any(
        isinstance(thread, dict)
        and isinstance(thread.get("role"), str) and thread["role"].strip()
        and isinstance(thread.get("parent_thread_id"), str) and thread["parent_thread_id"].strip()
        for thread in threads
    ):
        return False, "runtime capture lacks observed agent role/parent identity"
    token_usage = capture.get("tokens")
    if not isinstance(token_usage, dict):
        return False, "runtime capture token counters are missing"
    input_keys = [key for key in ("inputTokens", "input_tokens") if key in token_usage]
    output_keys = [key for key in ("outputTokens", "output_tokens") if key in token_usage]
    if len(input_keys) != 1 or len(output_keys) != 1:
        return False, "runtime capture must include input and output token counters"
    input_tokens = token_usage[input_keys[0]]
    output_tokens = token_usage[output_keys[0]]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (input_tokens, output_tokens)):
        return False, "runtime capture token counters are invalid"
    if trial.get("tokens") != input_tokens + output_tokens:
        return False, "trial token total differs from the observed capture counters"
    capture_duration = capture.get("duration_seconds")
    if (
        not nonnegative_number(capture_duration)
        or capture_duration <= 0
        or trial.get("duration_seconds") != capture_duration
    ):
        return False, "trial latency differs from observed runtime capture latency"
    return True, "PASS"


def valid_sha(value: Any, length: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(rf"[0-9a-f]{{{length}}}", value))


def valid_score(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and float(value) in SCORE_VALUES
    )


def load_rubric(path: str | Path | None, suite: dict[str, Any], suite_digest: str) -> tuple[Path, dict[str, Any], str]:
    selected_path = rubric_path(path)
    _, rubric, raw = evaluation_json(selected_path, label="rubric")
    validate_rubric(rubric, suite, suite_digest)
    return selected_path, rubric, sha256(raw)


def validate_rubric(rubric: dict[str, Any], suite: dict[str, Any], suite_digest: str) -> None:
    if rubric.get("rubric") != "delivery-size-v1-rubric" or rubric.get("version") != 1:
        raise ValueError("unsupported scoring rubric or version")
    if rubric.get("suite") != suite.get("suite") or rubric.get("suite_sha256") != suite_digest:
        raise ValueError("rubric does not match the pinned evaluation suite")
    if rubric.get("dimensions") != list(SCORING_DIMENSIONS):
        raise ValueError("rubric dimensions do not match the supported scoring dimensions")
    bootstrap = rubric.get("bootstrap")
    repeat_ids = suite.get("reliability_repeat_case_ids", [])
    if not isinstance(repeat_ids, list) or any(not isinstance(value, str) for value in repeat_ids):
        raise ValueError("suite reliability repeat IDs must be a string list")
    if (
        len(repeat_ids) != len(set(repeat_ids))
        or not set(repeat_ids) <= {
            case["id"] for case in suite["cases"] if case.get("partition") == "holdout"
        }
        or any(
            not any(case["id"] in repeat_ids and case.get("size") == size for case in suite["cases"])
            for size in {case.get("size") for case in suite["cases"] if case.get("partition") == "holdout"}
        )
    ):
        raise ValueError("suite reliability repeat IDs must be unique holdout cases stratified across sizes")
    expected_bootstrap = {
        "method": "sha256_cluster_percentile",
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "quantile_method": "type7",
        "confidence": 0.95,
        "minimum_holdout_scenarios": MINIMUM_HOLDOUT_SCENARIOS,
        "maximum_interval_half_width": MAX_INTERVAL_HALF_WIDTH,
        "threshold_exclusive": SCORE_THRESHOLD,
        "primary_attempts": 1,
        "reliability_repeats": "optional_preselected_stratified_subset",
        "reliability_repeat_case_ids": suite.get("reliability_repeat_case_ids", []),
        "reliability_repeats_default": suite.get("reliability_repeats_default", 0),
    }
    if bootstrap != expected_bootstrap:
        raise ValueError("rubric bootstrap settings differ from the preregistered method")
    rubric_cases = rubric.get("cases")
    if not isinstance(rubric_cases, dict) or set(rubric_cases) != {case["id"] for case in suite["cases"]}:
        raise ValueError("rubric must map every suite case exactly once")
    for case in suite["cases"]:
        rubric_case = rubric_cases[case["id"]]
        criteria = rubric_case.get("criteria") if isinstance(rubric_case, dict) else None
        if not isinstance(criteria, list) or not criteria:
            raise ValueError(f"{case['id']}: rubric criteria must be a non-empty list")
        ids: set[str] = set()
        represented_dimensions: set[str] = set()
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError(f"{case['id']}: each rubric criterion must be an object")
            criterion_id = criterion.get("id")
            dimension = criterion.get("dimension")
            weight = criterion.get("weight")
            judge_type = criterion.get("judge_type")
            if not isinstance(criterion_id, str) or not criterion_id or criterion_id in ids:
                raise ValueError(f"{case['id']}: criterion IDs must be unique non-empty strings")
            if not criterion_id.startswith(f"{case['id']}-C"):
                raise ValueError(f"{case['id']}: criterion ID must be namespaced to its case")
            if dimension not in SCORING_DIMENSIONS:
                raise ValueError(f"{case['id']}: invalid scoring dimension")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"{case['id']}: criterion weight must be positive and finite")
            if judge_type not in {"human", "deterministic"}:
                raise ValueError(f"{case['id']}: judge_type must be human or deterministic")
            if criterion.get("source") != case.get("source"):
                raise ValueError(f"{case['id']}: criterion source differs from suite source")
            if not isinstance(criterion.get("description"), str) or not criterion["description"].strip():
                raise ValueError(f"{case['id']}: criterion description is required")
            if "hard_fail" in criterion and not isinstance(criterion["hard_fail"], bool):
                raise ValueError(f"{case['id']}: hard_fail must be boolean")
            ids.add(criterion_id)
            represented_dimensions.add(dimension)
        if represented_dimensions != set(SCORING_DIMENSIONS):
            raise ValueError(f"{case['id']}: every scoring dimension must have a criterion")


def criterion_final_score(payload: dict[str, Any]) -> float:
    if not isinstance(payload, dict) or not valid_score(payload.get("score")):
        raise ValueError("criterion score must be 0, 0.5, or 1")
    reviewers = payload.get("reviewers")
    adjudicator = payload.get("adjudicator")
    if not isinstance(reviewers, list) or len(reviewers) != 2:
        raise ValueError("human score requires exactly two independent reviewer scores")
    reviewer_ids: set[str] = set()
    reviewer_scores: list[float] = []
    all_sufficient = True
    for reviewer in reviewers:
        if not isinstance(reviewer, dict) or not isinstance(reviewer.get("id"), str) or not reviewer["id"].strip():
            raise ValueError("reviewer identity is required")
        if not isinstance(reviewer.get("rationale"), str) or not reviewer["rationale"].strip():
            raise ValueError("reviewer rationale is required")
        if reviewer["id"] in reviewer_ids or not valid_score(reviewer.get("score")):
            raise ValueError("reviewers must be distinct and use the permitted score scale")
        if not isinstance(reviewer.get("evidence_sufficient"), bool):
            raise ValueError("reviewers must explicitly record evidence sufficiency")
        reviewer_ids.add(reviewer["id"])
        reviewer_scores.append(float(reviewer["score"]))
        all_sufficient = all_sufficient and reviewer["evidence_sufficient"]
    if reviewer_scores[0] == reviewer_scores[1] and all_sufficient:
        if adjudicator is not None or float(payload["score"]) != reviewer_scores[0]:
            raise ValueError("equal reviewer scores must be used directly without adjudication")
        return float(payload["score"])
    if not isinstance(adjudicator, dict) or not isinstance(adjudicator.get("id"), str) or not adjudicator["id"].strip():
        raise ValueError("disagreement or insufficient evidence requires an independent third reviewer")
    if (
        adjudicator["id"] in reviewer_ids
        or adjudicator.get("evidence_sufficient") is not True
        or not valid_score(adjudicator.get("score"))
        or not isinstance(adjudicator.get("rationale"), str)
        or not adjudicator["rationale"].strip()
    ):
        raise ValueError("adjudicator must be independent, confirm evidence, and use the permitted score scale")
    reviewer_scores.append(float(adjudicator["score"]))
    expected = float(statistics.median(reviewer_scores))
    if float(payload["score"]) != expected:
        raise ValueError("final human score must equal the median of reviewer/adjudicator scores")
    return expected


def score_dimensions(rubric_case: dict[str, Any], scores: dict[str, float]) -> tuple[dict[str, float], float]:
    criteria = rubric_case.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("rubric case has no criteria")
    expected_ids = {criterion["id"] for criterion in criteria}
    if not isinstance(scores, dict) or set(scores) != expected_ids:
        raise ValueError("scores must contain every rubric criterion exactly once")
    if any(not valid_score(value) for value in scores.values()):
        raise ValueError("criterion scores must be 0, 0.5, or 1")
    dimensions: dict[str, float] = {}
    for dimension in SCORING_DIMENSIONS:
        relevant = [criterion for criterion in criteria if criterion["dimension"] == dimension]
        if not relevant:
            raise ValueError(f"rubric case lacks dimension {dimension}")
        denominator = sum(float(criterion["weight"]) for criterion in relevant)
        numerator = sum(float(criterion["weight"]) * float(scores[criterion["id"]]) for criterion in relevant)
        dimensions[dimension] = 20.0 * numerator / denominator
    total = sum(dimensions.values())
    return dimensions, total


def type7_quantile(values: list[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise ValueError("quantile requires values and a probability in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_mean_ci(values: list[float], size: str) -> tuple[float, float]:
    if len(values) < MINIMUM_HOLDOUT_SCENARIOS:
        raise ValueError(f"at least {MINIMUM_HOLDOUT_SCENARIOS} independent holdout scores are required")
    if size not in {"small", "medium", "large"} or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100
        for value in values
    ):
        raise ValueError("bootstrap scores must be finite numbers in [0, 100] and size must be known")
    scenario_count = len(values)
    means: list[float] = []
    for replicate in range(BOOTSTRAP_REPLICATES):
        sample_total = 0.0
        for draw in range(scenario_count):
            material = f"delivery-size-v1|{size}|seed={BOOTSTRAP_SEED}|replicate={replicate}|draw={draw}".encode("utf-8")
            index = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % scenario_count
            sample_total += float(values[index])
        means.append(sample_total / scenario_count)
    return type7_quantile(means, 0.025), type7_quantile(means, 0.975)


def size_score_status(low: float, high: float, half_width: float) -> str:
    if any(not math.isfinite(value) for value in (low, high, half_width)) or low > high or half_width < 0:
        raise ValueError("confidence interval bounds are invalid")
    if high <= SCORE_THRESHOLD:
        return "FAIL"
    if low > SCORE_THRESHOLD and half_width <= MAX_INTERVAL_HALF_WIDTH:
        return "PASS"
    return "PENDING"


def _criterion_score_map(
    trial: dict[str, Any], rubric_case: dict[str, Any], record_dir: Path, case_id: str
) -> dict[str, float]:
    criteria = rubric_case["criteria"]
    results = trial.get("criterion_scores")
    expected = {criterion["id"] for criterion in criteria}
    if not isinstance(results, dict) or set(results) != expected:
        raise ValueError(f"{case_id}: criterion_scores must include every rubric criterion exactly once")
    scores: dict[str, float] = {}
    for criterion in criteria:
        criterion_id = criterion["id"]
        payload = results[criterion_id]
        if not isinstance(payload, dict) or not valid_score(payload.get("score")):
            raise ValueError(f"{case_id}/{criterion_id}: score is missing or invalid")
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not verify_evidence_reference(record_dir, item) for item in evidence):
            raise ValueError(f"{case_id}/{criterion_id}: evidence must be local and SHA-256 verified")
        if criterion["judge_type"] == "human":
            final = criterion_final_score(payload)
        else:
            judge = payload.get("judge")
            if (
                not isinstance(judge, dict)
                or judge.get("type") != "deterministic"
                or not isinstance(judge.get("name"), str) or not judge["name"].strip()
                or not isinstance(judge.get("command"), str) or not judge["command"].strip()
                or isinstance(judge.get("exit_code"), bool)
                or not isinstance(judge.get("exit_code"), int)
                or judge["exit_code"] != 0
                or not valid_score(judge.get("result_score"))
                or float(judge["result_score"]) != float(payload["score"])
                or not verify_evidence_reference(record_dir, judge.get("evidence"))
            ):
                raise ValueError(f"{case_id}/{criterion_id}: deterministic criterion requires a successful judge and evidence")
            final = float(payload["score"])
        scores[criterion_id] = final
    return scores


def evaluate_size(record_path: Path, record: dict[str, Any], suite: dict[str, Any], rubric: dict[str, Any], size: str) -> dict[str, Any]:
    holdout_cases = sorted([
        case for case in suite["cases"]
        if case.get("size") == size and case.get("partition") == "holdout"
    ], key=lambda case: case["id"])
    if len(holdout_cases) < MINIMUM_HOLDOUT_SCENARIOS:
        return {
            "size": size,
            "status": "PENDING",
            "reason": f"suite has {len(holdout_cases)} holdout scenarios; {MINIMUM_HOLDOUT_SCENARIOS} are required",
        }
    run_cases = {case["id"]: case for case in record.get("cases", []) if isinstance(case, dict)}
    missing_ids = sorted({case["id"] for case in holdout_cases} - set(run_cases))
    if missing_ids:
        return {"size": size, "status": "PENDING", "reason": "record omits required holdout scenarios"}
    if record.get("rubric", {}).get("sha256") != sha256(rubric_path(record.get("rubric", {}).get("file")).read_bytes()):
        return {"size": size, "status": "PENDING", "reason": "rubric fingerprint is missing or stale"}
    runtime = record.get("runtime", {})
    safety = record.get("safety", {})
    git = record.get("git", {})
    summary = record.get("summary", {})
    if runtime.get("name") in {None, "", "PENDING"} or runtime.get("version") in {None, "", "PENDING"}:
        return {"size": size, "status": "PENDING", "reason": "observed runtime name/version are required"}
    if runtime.get("profile_load_identity_verified") is not True:
        return {"size": size, "status": "PENDING", "reason": "runtime profile identity is unverified"}
    if safety.get("external_tools_mocked_fail_closed") is not True:
        return {"size": size, "status": "PENDING", "reason": "fail-closed external-tool evidence is required"}
    root_snapshot = record.get("root_instruction_source_snapshot")
    root_sources = root_snapshot.get("sources") if isinstance(root_snapshot, dict) else None
    if not isinstance(root_sources, dict) or set(root_sources) != {"project_agents", "global_agents"}:
        return {"size": size, "status": "PENDING", "reason": "project/global root instruction-source snapshots are required"}
    for source in root_sources.values():
        before = source.get("before_sha256") if isinstance(source, dict) else None
        after = source.get("after_sha256") if isinstance(source, dict) else None
        if not valid_sha(before, 64) or before == "MISSING" or after != before:
            return {"size": size, "status": "PENDING", "reason": "root instruction source hash is missing or changed during evaluation"}
    binding = record.get("profile_binding_config")
    if not isinstance(binding, dict) or not valid_sha(binding.get("before_sha256"), 64) or binding.get("after_sha256") != binding.get("before_sha256"):
        return {"size": size, "status": "PENDING", "reason": "project child-profile binding config hash is missing or changed"}
    if git.get("dirty") is not False or git.get("snapshot_reproducible") is not True:
        return {"size": size, "status": "PENDING", "reason": "a clean reproducible snapshot is required"}
    if not isinstance(summary.get("reviewer"), str) or not summary["reviewer"].strip():
        return {"size": size, "status": "PENDING", "reason": "human reviewer is required"}
    if summary.get("hard_fail") is True:
        return {"size": size, "status": "BLOCKED", "reason": "the run contains a recorded P0/P1 hard fail"}
    expected_repetitions = record.get("repetitions_requested")
    repeat_plan = record.get("reliability_repeat_plan")
    repeat_ids = repeat_plan.get("case_ids") if isinstance(repeat_plan, dict) else None
    repeat_count = repeat_plan.get("additional_attempts_per_case") if isinstance(repeat_plan, dict) else None
    allowed_repeat_ids = set(suite.get("reliability_repeat_case_ids", []))
    record_case_ids = {case["id"] for case in record.get("cases", []) if isinstance(case, dict) and isinstance(case.get("id"), str)}
    expected_repeat_ids = sorted(allowed_repeat_ids & record_case_ids) if isinstance(repeat_count, int) and repeat_count > 0 else []
    if (
        expected_repetitions != 1
        or not isinstance(repeat_ids, list)
        or repeat_ids != sorted(set(repeat_ids))
        or not set(repeat_ids) <= allowed_repeat_ids
        or repeat_ids != expected_repeat_ids
        or (isinstance(repeat_count, int) and repeat_count > 0 and not allowed_repeat_ids <= record_case_ids)
        or not isinstance(repeat_count, int)
        or isinstance(repeat_count, bool)
        or repeat_count < 0
        or ((repeat_count == 0) != (len(repeat_ids) == 0))
    ):
        return {"size": size, "status": "PENDING", "reason": "one primary attempt per scenario is required"}
    case_rubrics = rubric["cases"]
    case_reports: list[dict[str, Any]] = []
    scenario_totals: list[float] = []
    dimension_totals = {dimension: [] for dimension in SCORING_DIMENSIONS}
    tokens_total = 0.0
    latencies: list[float] = []
    reliability_repeat_tokens_total = 0.0
    reliability_repeat_trials = 0
    reliability_repeat_resolved = 0
    reliability_repeat_passes = 0
    primary_runtime_run_ids: set[str] = set()
    for suite_case in holdout_cases:
        run_case = run_cases[suite_case["id"]]
        trials = run_case.get("trials")
        expected_trial_count = 1 + (repeat_count if suite_case["id"] in repeat_ids else 0)
        if not isinstance(trials, list) or len(trials) != expected_trial_count or not trials:
            return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']} trial count differs from the preregistered attempt plan"}
        for trial in trials:
            if trial.get("status") == "BLOCKED" or any(
                isinstance(finding, dict) and str(finding.get("severity", "")).upper() in {"P0", "P1"}
                for finding in trial.get("findings", [])
            ):
                return {"size": size, "status": "BLOCKED", "reason": f"{suite_case['id']} has a P0/P1 finding"}
        primary_trial = trials[0]
        try:
            trial_run_id = primary_trial.get("runtime_run_id")
            if isinstance(trial_run_id, str) and trial_run_id in primary_runtime_run_ids:
                return {"size": size, "status": "PENDING", "reason": "primary holdout attempts must use independent runtime run IDs"}
            capture_ok, capture_reason = validate_capture_record(
                primary_trial.get("capture_record"),
                primary_trial.get("materialized_workspace_manifest"),
                record_path.resolve().parent,
                runtime,
                primary_trial,
            )
            if not capture_ok:
                return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']}: {capture_reason}"}
            primary_runtime_run_ids.add(trial_run_id)
            criterion_rubric = case_rubrics[suite_case["id"]]
            hard_fail_criteria: list[str] = []
            scores = _criterion_score_map(primary_trial, criterion_rubric, record_path.resolve().parent, suite_case["id"])
            for criterion in criterion_rubric["criteria"]:
                if criterion.get("hard_fail") is True and scores[criterion["id"]] < 1.0:
                    hard_fail_criteria.append(criterion["id"])
            for repeat_trial in trials[1:]:
                repeat_scores_payload = repeat_trial.get("criterion_scores")
                hard_fail_rubric = {
                    "criteria": [criterion for criterion in criterion_rubric["criteria"] if criterion.get("hard_fail") is True]
                }
                hard_fail_ids = {criterion["id"] for criterion in hard_fail_rubric["criteria"]}
                if hard_fail_ids and isinstance(repeat_scores_payload, dict) and all(
                    repeat_scores_payload.get(criterion_id) is not None for criterion_id in hard_fail_ids
                ):
                    hard_fail_trial = {
                        **repeat_trial,
                        "criterion_scores": {
                            criterion_id: repeat_scores_payload[criterion_id] for criterion_id in hard_fail_ids
                        },
                    }
                    repeat_scores = _criterion_score_map(hard_fail_trial, hard_fail_rubric, record_path.resolve().parent, suite_case["id"])
                    hard_fail_criteria.extend(
                        criterion_id for criterion_id in hard_fail_ids if repeat_scores[criterion_id] < 1.0
                    )
            if hard_fail_criteria:
                hard_fail_criteria = sorted(set(hard_fail_criteria))
                return {
                    "size": size,
                    "status": "BLOCKED",
                    "reason": f"{suite_case['id']} failed hard-fail criterion(s): {', '.join(hard_fail_criteria)}",
                    "hard_fail_criteria": hard_fail_criteria,
                }
            if primary_trial.get("status") != "PASS":
                return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']} primary attempt is not PASS"}
            if primary_trial.get("profile_load_identity_verified") is not True:
                return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']} primary attempt lacks runtime profile identity"}
            if not nonnegative_number(primary_trial.get("tokens")) or primary_trial.get("tokens") is None:
                return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']} primary attempt lacks observed token telemetry"}
            if primary_trial.get("duration_seconds") is None or not nonnegative_number(primary_trial.get("duration_seconds")):
                return {"size": size, "status": "PENDING", "reason": f"{suite_case['id']} primary attempt lacks observed latency"}
            case_dimensions, case_total = score_dimensions(case_rubrics[suite_case["id"]], scores)
        except (KeyError, ValueError) as exc:
            return {"size": size, "status": "PENDING", "reason": str(exc)}
        tokens_total += float(primary_trial["tokens"])
        reliability_trials = trials[1:]
        reliability_statuses = [trial.get("status") for trial in reliability_trials]
        reliability_resolved = [status for status in reliability_statuses if status in {"PASS", "FAIL"}]
        reliability_tokens = [trial["tokens"] for trial in reliability_trials if nonnegative_number(trial.get("tokens")) and trial.get("tokens") is not None]
        reliability_repeat_tokens_total += sum(float(value) for value in reliability_tokens)
        reliability_repeat_trials += len(reliability_trials)
        reliability_repeat_resolved += len(reliability_resolved)
        reliability_repeat_passes += reliability_resolved.count("PASS")
        latencies.append(float(primary_trial["duration_seconds"]))
        scenario_totals.append(case_total)
        for dimension in SCORING_DIMENSIONS:
            dimension_totals[dimension].append(case_dimensions[dimension])
        case_reports.append({
            "case_id": suite_case["id"],
            "score": case_total,
            "primary_attempt_score": case_total,
            "dimensions": case_dimensions,
            "reliability_repeat_count": len(reliability_trials),
            "reliability_repeat_passes": reliability_resolved.count("PASS"),
            "reliability_repeat_resolved": len(reliability_resolved),
        })
    low, high = bootstrap_mean_ci(scenario_totals, size)
    mean_score = statistics.mean(scenario_totals)
    half_width = (high - low) / 2.0
    status = size_score_status(low, high, half_width)
    return {
        "size": size,
        "status": status,
        "mean_score": mean_score,
        "confidence_interval_95": [low, high],
        "interval_half_width": half_width,
        "holdout_scenarios": len(scenario_totals),
        "primary_trials": len(scenario_totals),
        "reliability_repeat_trials": reliability_repeat_trials,
        "reliability_repeat_pass_rate": (
            reliability_repeat_passes / reliability_repeat_resolved
            if reliability_repeat_resolved else None
        ),
        "reliability_repeat_tokens_total": reliability_repeat_tokens_total,
        "dimensions": {dimension: statistics.mean(values) for dimension, values in dimension_totals.items()},
        "observed_tokens_total": tokens_total,
        "observed_latency_median_seconds": statistics.median(latencies),
        "cost_analysis": "N/A (billing source/rate card not available)",
        "observed_cost_total": None,
        "scenario_scores": case_reports,
    }


def nonnegative_number(value: Any) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value >= 0
    )


def prepare(args: argparse.Namespace) -> Path:
    selected_suite_path = suite_path(args.suite)
    suite = load_suite(selected_suite_path)
    is_delivery_size_suite = suite.get("suite") == "delivery-size-v1"
    runs_requested = args.runs if args.runs is not None else (1 if is_delivery_size_suite else 3)
    if runs_requested < 1:
        raise ValueError("--runs must be at least 1")
    reliability_repeats = args.reliability_repeats
    if reliability_repeats < 0:
        raise ValueError("--reliability-repeats cannot be negative")
    if is_delivery_size_suite and runs_requested != 1:
        raise ValueError("delivery-size uses exactly one primary attempt; use --reliability-repeats for the preregistered subset")
    suite_digest = sha256(selected_suite_path.read_bytes())
    selected_rubric_path: Path | None = None
    rubric: dict[str, Any] | None = None
    rubric_digest: str | None = None
    if is_delivery_size_suite:
        selected_rubric_path, rubric, rubric_digest = load_rubric(None, suite, suite_digest)
    selected = set(args.case or [case["id"] for case in suite["cases"]])
    unknown = selected - {case["id"] for case in suite["cases"]}
    if unknown:
        raise ValueError(f"unknown case(s): {', '.join(sorted(unknown))}")
    chosen = [case for case in suite["cases"] if case["id"] in selected]
    reliability_case_ids = suite.get("reliability_repeat_case_ids", []) if is_delivery_size_suite else []
    holdout_ids = {case["id"] for case in suite["cases"] if case.get("partition") == "holdout"}
    if not isinstance(reliability_case_ids, list) or any(not isinstance(value, str) for value in reliability_case_ids):
        raise ValueError("suite reliability_repeat_case_ids must be a string list")
    if len(reliability_case_ids) != len(set(reliability_case_ids)):
        raise ValueError("suite reliability_repeat_case_ids must be a unique case ID list")
    if not set(reliability_case_ids) <= holdout_ids:
        raise ValueError("reliability repeats may only be preregistered for holdout cases")
    repeat_ids_selected = sorted(set(reliability_case_ids) & selected) if reliability_repeats else []
    if reliability_repeats and set(repeat_ids_selected) != set(reliability_case_ids):
        raise ValueError("reliability repeats require the full preregistered stratified case subset in the selected run")
    per_case_repetitions = {
        case["id"]: (
            1 + (reliability_repeats if case["id"] in repeat_ids_selected else 0)
            if is_delivery_size_suite else runs_requested
        )
        for case in chosen
    }
    commit = git_output("rev-parse", "HEAD")
    status_bytes = git_bytes("status", "--porcelain=v1", "-z")
    dirty = bool(status_bytes)
    if dirty and not args.allow_dirty:
        raise ValueError("worktree is dirty; prepare from a clean, committed snapshot (or use --allow-dirty only for local harness validation)")
    diff_hash = sha256(git_bytes("diff", "--binary", "HEAD"))
    profiles = fingerprints(profile_dir(args.profiles), suite)
    profile_binding_config = {
        "source_id": "project/.codex/config.toml",
        "before_sha256": file_sha256(ROOT / ".codex/config.toml"),
        "after_sha256": None,
    }
    run = {
        "schema_version": 1,
        "suite": suite["suite"],
        "suite_file": selected_suite_path.relative_to(ROOT).as_posix(),
        "suite_sha256": suite_digest,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": ROOT.name,
        "git": {"branch": git_output("branch", "--show-current"), "commit": commit, "dirty": dirty,
                "snapshot_reproducible": not dirty, "status_sha256": sha256(status_bytes),
                "tracked_diff_sha256": diff_hash},
        "runtime": {"name": "PENDING", "version": "PENDING", "profile_load_identity_verified": False},
        "root_instruction_source_snapshot": root_instruction_snapshot(),
        "root_agent": {"role": ROOT_AGENT_ROLE, "identity_basis": "instruction_source_snapshot"},
        "profile_binding_config": profile_binding_config,
        "profiles": {"source_directory": profile_source_identifier(args.profiles), "sha256": profiles},
        "repetitions_requested": runs_requested,
        **({"reliability_repeat_plan": {
            "case_ids": repeat_ids_selected,
            "additional_attempts_per_case": reliability_repeats if repeat_ids_selected else 0,
        }} if is_delivery_size_suite else {}),
        "selected_case_ids": [case["id"] for case in chosen],
        "safety": {"isolated_fixture_or_worktree": False, "external_tools_mocked_fail_closed": False, "operator_note": "Set true only after recording the actual isolated setup and blocked external tools."},
        "cases": [
            {
                "id": case["id"], "title": case["title"], "risk": case["risk"],
                "required_profiles": child_profiles(case), "source": case["source"],
                "root_agent": ROOT_AGENT_ROLE,
                **({"size": case["size"], "partition": case["partition"]} if "size" in case and "partition" in case else {}),
                "trials": [
                    {"attempt": i + 1, "status": "NOT RUN", "profile_load_identity_verified": False,
                     "observed_profiles": {
                         name: {
                             "identity_verified": False,
                             "sha256": None,
                             "effective_config_path": project_profile_config_file(name),
                             "effective_config_sha256_before": project_profile_config_sha(name),
                             "effective_config_sha256_after": None,
                         }
                         for name in child_profiles(case)
                     },
                     "evidence": [], "deterministic_judges": [], "duration_seconds": None,
                     "tokens": None, "cost": None, "findings": [],
                     **({"runtime_run_id": None, "capture_record": None, "materialized_workspace_manifest": None} if is_delivery_size_suite else {})}
                    for i in range(per_case_repetitions[case["id"]])
                ]
            }
            for case in chosen
        ],
        "summary": {"status": "PENDING", "reviewer": None, "hard_fail": False, "notes": []},
    }
    if rubric is not None and selected_rubric_path is not None and rubric_digest is not None:
        run["rubric"] = {
            "file": selected_rubric_path.relative_to(ROOT).as_posix(),
            "sha256": rubric_digest,
            "version": rubric["version"],
        }
        for case_record in run["cases"]:
            case_record["trials"] = [
                {
                    **trial,
                    "run_purpose": "primary" if trial["attempt"] == 1 else "reliability_repeat",
                    "reliability_repeat_index": trial["attempt"] - 1 if trial["attempt"] > 1 else None,
                }
                for trial in case_record["trials"]
            ]
            case_record["trials"] = [
                {
                    **trial,
                    "criterion_scores": {
                        criterion["id"]: None
                        for criterion in rubric["cases"][case_record["id"]]["criteria"]
                    },
                    "observed_profiles": {
                        name: {
                            "identity_verified": False,
                            "sha256": None,
                            "effective_config_path": project_profile_config_file(name),
                            "effective_config_sha256_before": project_profile_config_sha(name),
                            "effective_config_sha256_after": None,
                        }
                        for name in case_record["required_profiles"]
                    },
                }
                for trial in case_record["trials"]
            ]
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
    resolved_record_path = path.expanduser().resolve()
    if not resolved_record_path.is_file() or resolved_record_path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("run record is missing or exceeds the configured size limit")
    record = json.loads(resolved_record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("run record must be a JSON object")
    suite_file = record.get("suite_file", "docs/evaluations/agent-workflow-v1.json")
    selected_suite_path = suite_path(suite_file)
    suite = load_suite(selected_suite_path)
    if record.get("suite") != suite["suite"]:
        raise ValueError("record suite does not match current suite")
    if not valid_sha(record.get("suite_sha256"), 64) or record["suite_sha256"] != sha256(selected_suite_path.read_bytes()):
        raise ValueError("record suite hash is stale; prepare a new run for the current suite")
    selected_rubric_path: Path | None = None
    rubric: dict[str, Any] | None = None
    if "rubric" in record:
        rubric_info = record.get("rubric")
        if not isinstance(rubric_info, dict) or not valid_sha(rubric_info.get("sha256"), 64):
            raise ValueError("record rubric fingerprint is invalid")
        selected_rubric_path, rubric, rubric_digest = load_rubric(
            rubric_info.get("file"), suite, record["suite_sha256"]
        )
        if rubric_info["sha256"] != rubric_digest or rubric_info.get("version") != rubric["version"]:
            raise ValueError("record rubric fingerprint/version is stale")
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
    selected = set(selected_list)
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
        if case.get("required_profiles") != child_profiles(expected_case):
            raise ValueError(f"{case_id}: required_profiles differ from the versioned suite")
        if case.get("root_agent") != ROOT_AGENT_ROLE:
            raise ValueError(f"{case_id}: root agent must be identified by instruction-source snapshot")
        for field in ("size", "partition"):
            if field in expected_case and case.get(field) != expected_case[field]:
                raise ValueError(f"{case_id}: {field} differs from the versioned suite")
        trials = case.get("trials")
        if rubric is not None:
            repeat_plan = record.get("reliability_repeat_plan")
            if not isinstance(repeat_plan, dict):
                raise ValueError("delivery-size record requires a reliability repeat plan")
            repeat_ids = repeat_plan.get("case_ids")
            repeat_count = repeat_plan.get("additional_attempts_per_case")
            allowed_repeat_ids = set(suite.get("reliability_repeat_case_ids", []))
            expected_repeat_ids = sorted(allowed_repeat_ids & selected) if isinstance(repeat_count, int) and repeat_count > 0 else []
            if (
                not isinstance(repeat_ids, list)
                or any(not isinstance(value, str) for value in repeat_ids)
                or repeat_ids != sorted(set(repeat_ids))
                or not set(repeat_ids) <= allowed_repeat_ids
                or not set(repeat_ids) <= selected
                or repeat_ids != expected_repeat_ids
                or (isinstance(repeat_count, int) and repeat_count > 0 and not allowed_repeat_ids <= selected)
                or not isinstance(repeat_count, int)
                or isinstance(repeat_count, bool)
                or repeat_count < 0
                or ((repeat_count == 0) != (len(repeat_ids) == 0))
            ):
                raise ValueError("delivery-size reliability repeat plan is invalid or not preregistered")
            if repeat_count and case_id not in repeat_ids:
                expected_trial_count = 1
            else:
                expected_trial_count = 1 + (repeat_count if case_id in repeat_ids else 0)
        else:
            expected_trial_count = repetitions
        if not isinstance(trials, list) or len(trials) != expected_trial_count:
            raise ValueError(f"{case['id']}: trial count does not match its requested attempt plan")
        for index, trial in enumerate(trials):
            if not isinstance(trial, dict):
                raise ValueError(f"{case['id']}: each trial must be a JSON object")
            attempt = trial.get("attempt")
            if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt != index + 1:
                raise ValueError(f"{case['id']}: attempts must be numbered sequentially from 1")
            if rubric is not None:
                expected_purpose = "primary" if attempt == 1 else "reliability_repeat"
                if trial.get("run_purpose") != expected_purpose:
                    raise ValueError(f"{case['id']}: attempt purpose differs from the preregistered plan")
                expected_repeat_index = attempt - 1 if attempt > 1 else None
                if trial.get("reliability_repeat_index") != expected_repeat_index:
                    raise ValueError(f"{case['id']}: reliability repeat index is invalid")
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
                    if rubric is not None:
                        effective_path = project_profile_config_file(profile_name)
                        config_before = observation.get("effective_config_sha256_before")
                        config_after = observation.get("effective_config_sha256_after")
                        if observation.get("effective_config_path") != effective_path:
                            raise ValueError(f"{case['id']}: {profile_name} effective config path is not the project mapping")
                        if not valid_sha(config_before, 64) or config_before != loaded_sha or config_after != config_before:
                            raise ValueError(f"{case['id']}: {profile_name} effective config hash changed or is missing")
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
            if rubric is not None:
                criterion_scores = trial.get("criterion_scores")
                criterion_ids = {item["id"] for item in rubric["cases"][case["id"]]["criteria"]}
                if not isinstance(criterion_scores, dict) or set(criterion_scores) != criterion_ids:
                    raise ValueError(f"{case['id']}: criterion_scores must match pinned rubric IDs")
                for criterion in rubric["cases"][case["id"]]["criteria"]:
                    payload = criterion_scores[criterion["id"]]
                    if payload is None:
                        continue
                    if not isinstance(payload, dict) or not valid_score(payload.get("score")):
                        raise ValueError(f"{case['id']}/{criterion['id']}: score payload is invalid")
                    evidence = payload.get("evidence")
                    if not isinstance(evidence, list) or not evidence or any(
                        not verify_evidence_reference(resolved_record_path.parent, item) for item in evidence
                    ):
                        raise ValueError(f"{case['id']}/{criterion['id']}: evidence must be local and SHA-256 verified")
                    if criterion["judge_type"] == "human":
                        criterion_final_score(payload)
                    else:
                        judge = payload.get("judge")
                        if (
                            not isinstance(judge, dict)
                            or judge.get("type") != "deterministic"
                            or not isinstance(judge.get("name"), str) or not judge["name"].strip()
                            or not isinstance(judge.get("command"), str) or not judge["command"].strip()
                            or isinstance(judge.get("exit_code"), bool)
                            or not isinstance(judge.get("exit_code"), int)
                            or judge["exit_code"] != 0
                            or not valid_score(judge.get("result_score"))
                            or float(judge["result_score"]) != float(payload["score"])
                            or not verify_evidence_reference(resolved_record_path.parent, judge.get("evidence"))
                        ):
                            raise ValueError(f"{case['id']}/{criterion['id']}: deterministic judge evidence is invalid")
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
        if record.get("suite") == "delivery-size-v1":
            root_snapshot = record.get("root_instruction_source_snapshot")
            sources = root_snapshot.get("sources") if isinstance(root_snapshot, dict) else None
            if not isinstance(sources, dict) or set(sources) != {"project_agents", "global_agents"}:
                raise ValueError("summary PASS requires project and global root instruction-source snapshots")
            for source in sources.values():
                before = source.get("before_sha256") if isinstance(source, dict) else None
                after = source.get("after_sha256") if isinstance(source, dict) else None
                if not valid_sha(before, 64) or before == "MISSING" or after != before:
                    raise ValueError("summary PASS requires matching project/global AGENTS hashes before and after")
            binding = record.get("profile_binding_config")
            if not isinstance(binding, dict) or not valid_sha(binding.get("before_sha256"), 64) or binding.get("after_sha256") != binding.get("before_sha256"):
                raise ValueError("summary PASS requires a stable project profile-binding config hash")
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
    if any("size" in case for case in record["cases"]):
        print("\nSize | Partition | Cases | Resolved trials | Pass rate")
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for case in record["cases"]:
            if "size" in case:
                groups.setdefault((case["size"], case["partition"]), []).append(case)
        for (size, partition), cases in sorted(groups.items()):
            trials = [trial for case in cases for trial in case["trials"]]
            resolved = [trial for trial in trials if trial["status"] in {"PASS", "FAIL"}]
            passed = sum(trial["status"] == "PASS" for trial in resolved)
            rate = f"{passed}/{len(resolved)}" if resolved else "N/A"
            print(f"{size} | {partition} | {len(cases)} | {len(resolved)}/{len(trials)} | {rate}")
    print("N/A means runtime telemetry was not recorded; no cost or duration was estimated.")


def score_record(path: Path, selected_size: str | None = None) -> dict[str, Any]:
    validate_record(path)
    resolved = path.expanduser().resolve()
    if resolved.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("run record exceeds the configured size limit")
    record = json.loads(resolved.read_text(encoding="utf-8"))
    suite_file = record.get("suite_file")
    selected_suite_path = suite_path(suite_file)
    suite = load_suite(selected_suite_path)
    rubric_info = record.get("rubric")
    if not isinstance(rubric_info, dict):
        raise ValueError("run record has no pinned scoring rubric")
    rubric_path_value = rubric_info.get("file")
    _, rubric, rubric_digest = load_rubric(rubric_path_value, suite, record["suite_sha256"])
    if rubric_info.get("sha256") != rubric_digest:
        raise ValueError("run rubric fingerprint is stale")
    available_sizes = sorted({
        case["size"] for case in suite["cases"] if case.get("size") in {"small", "medium", "large"}
    })
    sizes = [selected_size] if selected_size else available_sizes
    if not sizes or any(size not in available_sizes for size in sizes):
        raise ValueError("requested size is not present in the versioned suite")
    return {
        "schema_version": 1,
        "suite": suite["suite"],
        "suite_sha256": record["suite_sha256"],
        "rubric_sha256": rubric_digest,
        "record_sha256": sha256(resolved.read_bytes()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": [evaluate_size(resolved, record, suite, rubric, size) for size in sizes],
    }


def write_score_report(report: dict[str, Any], output: str | Path) -> Path:
    candidate = Path(output).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(EVALUATIONS_DIR)
    except ValueError as exc:
        raise ValueError("score report output must be within docs/evaluations") from exc
    if candidate.suffix != ".json":
        raise ValueError("score report output must use the .json extension")
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(serialized.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("score report exceeds the configured size limit")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    with candidate.open("x", encoding="utf-8") as stream:
        stream.write(serialized)
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="create a pinned PENDING run record")
    prepare_parser.add_argument("--case", action="append", help="case ID; repeat to select multiple")
    prepare_parser.add_argument("--runs", type=int, help="trials requested per case (legacy suites default to 3; delivery-size is fixed at 1)")
    prepare_parser.add_argument("--reliability-repeats", type=int, default=0,
                                help="additional trials for suite-preregistered holdout IDs only (delivery-size suites)")
    prepare_parser.add_argument("--profiles", help="directory with TOML profiles; defaults to CODEX_HOME/agents or repo agents/")
    prepare_parser.add_argument("--output", help="output JSON path")
    prepare_parser.add_argument("--suite", help="versioned suite JSON inside docs/evaluations; defaults to agent-workflow-v1.json")
    prepare_parser.add_argument("--allow-dirty", action="store_true", help="development-only: prepare a non-reproducible PENDING record; such a run can never PASS")
    validate_parser = subparsers.add_parser("validate", help="validate a completed or pending run record")
    validate_parser.add_argument("record", type=Path)
    report_parser = subparsers.add_parser("report", help="summarize pass consistency and observed duration/cost")
    report_parser.add_argument("record", type=Path)
    score_parser = subparsers.add_parser("score", help="score delivery-size holdouts using the pinned rubric and confidence interval")
    score_parser.add_argument("record", type=Path)
    score_parser.add_argument("--size", choices=("small", "medium", "large"), help="score one size; by default report every size in the suite")
    score_parser.add_argument("--output", required=True, help="new JSON report path within docs/evaluations")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "validate":
            validate_record(args.record)
        elif args.command == "report":
            report_record(args.record)
        else:
            report = score_record(args.record, args.size)
            output = write_score_report(report, args.output)
            print(f"Score report: {output}")
            for result in report["results"]:
                print(f"{result['size']}: {result['status']}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Agent eval error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

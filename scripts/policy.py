#!/usr/bin/env python3
"""Deterministic workflow risk classifier. It does not authorize actions."""
from __future__ import annotations
import json
import math
import sys
from pathlib import PurePosixPath

# Thresholds are provisional routing signals, not calibrated limits.
CLASS_C_PATHS = ("migrations", "auth", ".github/workflows")
TASK_FIELDS = {
    "paths", "irreversible", "money", "external_submission",
    "major_dependency_change", "license_change", "scope_expansion",
    "diff_lines", "cost_ratio", "new_dependency", "reversible_schema_change",
    "public_api_change", "retry", "files_touched",
}

def classify(task: dict) -> tuple[str, list[str]]:
    if not isinstance(task, dict):
        return "C", ["invalid_task_shape"]
    if not task:
        return "C", ["empty_task"]
    if any(not isinstance(key, str) for key in task):
        return "C", ["invalid_task_fields"]
    unknown_fields = set(task) - TASK_FIELDS
    if unknown_fields:
        return "C", ["unknown_task_fields"]
    reasons: list[str] = []
    paths = task.get("paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p.strip() for p in paths):
        return "C", ["invalid_paths"]
    for raw in paths:
        path = PurePosixPath(raw.replace("\\", "/"))
        parts = path.parts
        if (any(part in ("migrations", "auth") for part in parts)
                or ".github" in parts and "workflows" in parts
                or any(part.startswith(".env") for part in parts)
                or any(part.endswith(".crypto") or ".crypto." in part for part in parts)):
            reasons.append(f"class_c_path:{raw}")
    flags_c = ("irreversible", "money", "external_submission", "major_dependency_change", "license_change", "scope_expansion")
    flags_b = ("new_dependency", "reversible_schema_change", "public_api_change")
    for flag in (*flags_c, *flags_b):
        if flag in task and not isinstance(task[flag], bool):
            return "C", [f"invalid_boolean:{flag}"]
    for flag in flags_c:
        if task.get(flag) is True:
            reasons.append(flag)
    lines = task.get("diff_lines")
    if lines is not None and (not isinstance(lines, int) or isinstance(lines, bool) or lines < 0):
        return "C", ["invalid_diff_lines"]
    if isinstance(lines, int) and lines > 800:
        reasons.append("diff_lines_over_provisional_800")
    ratio = task.get("cost_ratio")
    try:
        ratio_valid = ratio is None or (isinstance(ratio, (int, float)) and not isinstance(ratio, bool)
                                        and math.isfinite(ratio) and ratio >= 0)
    except (OverflowError, TypeError):
        ratio_valid = False
    if not ratio_valid:
        return "C", ["invalid_cost_ratio"]
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
        if ratio > 2.0:
            reasons.append("cost_ratio_over_provisional_2")
        elif ratio > 1.0:
            # B unless a C signal already exists
            pass
    if reasons:
        return "C", reasons
    bflags = ("new_dependency", "reversible_schema_change", "public_api_change")
    for flag in bflags:
        if task.get(flag) is True:
            reasons.append(flag)
    retries = task.get("retry")
    if retries is not None and (not isinstance(retries, int) or isinstance(retries, bool) or retries < 0):
        return "C", ["invalid_retry"]
    if isinstance(retries, int) and retries >= 2:
        reasons.append("retry_at_least_2")
    files = task.get("files_touched")
    if files is not None and (not isinstance(files, int) or isinstance(files, bool) or files < 0):
        return "C", ["invalid_files_touched"]
    if isinstance(files, int) and files > 15:
        reasons.append("files_touched_over_provisional_15")
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio > 1.0:
        reasons.append("cost_ratio_over_provisional_1")
    return ("B", reasons) if reasons else ("A", ["default_low_risk"])

def main() -> int:
    try:
        task = json.load(sys.stdin)
        category, reasons = classify(task)
        print(json.dumps({"class": category, "reasons": reasons, "authorizes_action": False}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError) as exc:
        print(json.dumps({"class": "C", "reasons": ["invalid_json_or_task"], "error": str(exc), "authorizes_action": False}), file=sys.stdout)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate this repo's playbook using the pinned Alethe upstream parser.

This intentionally imports no parser bundled into this repository. Supply the
reviewed Alethe skill checkout; mismatched upstream source fails closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "docs/agent-delivery/alethe-playbooks.yaml"
EXPECTED_COMMIT = "ab8110457d0126737f1a0dea2c312bb4f024c50f"
EXPECTED_ORIGIN = "https://github.com/Kc1t/alethe-orchestrate-skill"


def git_value(repo: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alethe-skill-path", required=True, type=Path, help="Path to the pinned Alethe skills/alethe directory")
    parser.add_argument("--playbook-path", type=Path, default=PLAYBOOK, help="Playbook YAML to validate (default: repo template)")
    parser.add_argument("--require-pinned-models", action="store_true", help="Reject any tier without explicit, distinct Codex/Claude model IDs")
    args = parser.parse_args()
    skill = args.alethe_skill_path.expanduser().resolve()
    repo = skill.parent.parent
    if git_value(repo, "remote", "get-url", "origin") != EXPECTED_ORIGIN:
        raise ValueError("Alethe origin does not match the audited upstream")
    if git_value(repo, "rev-parse", "--verify", "HEAD") != EXPECTED_COMMIT:
        raise ValueError(f"Alethe commit differs from audited parser pin {EXPECTED_COMMIT}")
    source = skill / "scripts/orchestrate.py"
    if not source.is_file():
        raise ValueError(f"Alethe parser not found: {source}")
    spec = importlib.util.spec_from_file_location("alethe_upstream_orchestrate", source)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned Alethe parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    playbook_path = args.playbook_path.expanduser().resolve()
    text = playbook_path.read_text(encoding="utf-8")
    data = module.parse_playbooks_yaml(text)
    errors = module.playbook_structure_errors(data)
    if errors:
        raise ValueError("Alethe playbook schema errors:\n" + "\n".join(errors))
    phases = data["playbooks"]["idea-to-delivery"]["phases"]
    if not {
        "refine_codex", "refine_claude", "critique_codex", "critique_claude",
        "task_review_codex", "task_review_claude", "task_review_final_codex",
        "task_review_final_claude", "code_review",
    } <= {p["id"] for p in phases}:
        raise ValueError("playbook is missing a required cross-provider or review phase")
    if args.require_pinned_models:
        for tier_name in ("cheap", "standard", "strong"):
            tier = data.get("tiers", {}).get(tier_name, {})
            models = {provider: tier.get(provider, {}).get("model") for provider in ("codex", "claude")}
            if not all(isinstance(model, str) and model.strip() for model in models.values()):
                raise ValueError(f"tier {tier_name} requires explicit model IDs for codex and claude")
            if models["codex"] == models["claude"]:
                raise ValueError(f"tier {tier_name} requires different model IDs for codex and claude")
    status = "pinned models required and present" if args.require_pinned_models else "models not verified; validation is structural only"
    print(f"Alethe playbook: PASS (upstream parser {EXPECTED_COMMIT}, {len(phases)} phases; {status}; no provider invoked)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AttributeError, KeyError) as exc:
        print(f"Alethe playbook: FAIL\n{exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Validate this Codex agent package and exercise installer behavior in isolation."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "agents"
README = ROOT / "README.md"
INSTALLER = ROOT / "install-agents.sh"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
AGENT_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def heading_section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"README section not found: {heading}")
    following = re.search(r"^## ", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[match.end() : end]


def validate_profiles() -> set[str]:
    paths = sorted(AGENTS_DIR.glob("*.toml"))
    if not paths:
        raise ValueError("no agents/*.toml profiles found")

    names: set[str] = set()
    for path in paths:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path.relative_to(ROOT)} has no non-empty name")
        if name != path.stem:
            raise ValueError(f"{path.name}: TOML name {name!r} must match filename stem")
        if not isinstance(data.get("description"), str) or not data["description"].strip():
            raise ValueError(f"{path.name} has no non-empty description")
        if not isinstance(data.get("developer_instructions"), str):
            raise ValueError(f"{path.name} has no developer_instructions string")
        if name in names:
            raise ValueError(f"duplicate agent name: {name}")
        names.add(name)
    print(f"TOML profiles: PASS ({len(paths)})")
    return names


def validate_readme_manifest(names: set[str]) -> None:
    text = README.read_text(encoding="utf-8")
    sections = [heading_section(text, "Agents"), heading_section(text, "Skills e ferramentas por agente")]
    for section_name, section in zip(("Agents", "Skills e ferramentas por agente"), sections):
        listed = set(AGENT_ROW.findall(section))
        missing = names - listed
        stale = listed - names
        if missing or stale:
            raise ValueError(
                f"README section {section_name!r} differs from agents/*.toml; "
                f"missing={sorted(missing)}, stale={sorted(stale)}"
            )
    print("README agent tables: PASS (both tables match profile filenames)")


def markdown_files() -> list[Path]:
    return [ROOT / "README.md", ROOT / "EXAMPLE.md", *sorted((ROOT / "docs").rglob("*.md"))]


def validate_local_markdown_links() -> None:
    broken: list[str] = []
    for markdown in markdown_files():
        text = markdown.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip("<>")
            if target.startswith(("https://", "http://", "mailto:", "#", "//")):
                continue
            target_path = target.split("#", 1)[0].split("?", 1)[0]
            if not target_path:
                continue
            candidate = (markdown.parent / target_path).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                broken.append(f"{markdown.relative_to(ROOT)}: link escapes repository: {target}")
                continue
            if not candidate.exists():
                broken.append(f"{markdown.relative_to(ROOT)}: missing local link: {target}")
    if broken:
        raise ValueError("\n".join(broken))
    print(f"Markdown local links: PASS ({len(markdown_files())} files scanned)")


def run_installer(args: list[str], codex_home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def validate_installer_isolation(names: set[str]) -> None:
    source_files = {path.name: path.read_bytes() for path in AGENTS_DIR.glob("*.toml")}
    with tempfile.TemporaryDirectory(prefix="agent-package-validation-") as temp:
        temporary_root = Path(temp)
        dry_home = temporary_root / "dry-run-home"
        dry = run_installer(["--dry-run"], dry_home)
        if dry.returncode != 0:
            raise ValueError(f"isolated dry-run failed ({dry.returncode}):\n{dry.stdout}")
        if (dry_home / "agents").exists():
            raise ValueError("installer --dry-run wrote to CODEX_HOME")

        codex_home = temporary_root / "codex-home"
        destination = codex_home / "agents"
        destination.mkdir(parents=True)
        previous_profile = b"previous custom profile for rollback smoke test\n"
        (destination / "product-lead.toml").write_bytes(previous_profile)
        original_names = {"product-lead.toml"}

        installed = run_installer(["--replace"], codex_home)
        if installed.returncode != 0:
            raise ValueError(f"isolated install failed ({installed.returncode}):\n{installed.stdout}")
        backup_match = re.search(r"^Backup dos conflitos: (.+)$", installed.stdout, re.MULTILINE)
        if not backup_match:
            raise ValueError(f"installer did not report a conflict backup:\n{installed.stdout}")
        backup_dir = Path(backup_match.group(1))
        if stat.S_IMODE(backup_dir.stat().st_mode) != 0o700:
            raise ValueError("installer backup directory is not mode 0700")
        if (backup_dir / "product-lead.toml").read_bytes() != previous_profile:
            raise ValueError("installer conflict backup does not preserve previous content")

        installed_names = {path.name for path in destination.glob("*.toml")}
        if installed_names != set(source_files) or len(installed_names) != len(names):
            raise ValueError(f"isolated install file set mismatch: {sorted(installed_names)}")
        for name, contents in source_files.items():
            target = destination / name
            if target.read_bytes() != contents:
                raise ValueError(f"installed content differs from source: {name}")
            if stat.S_IMODE(target.stat().st_mode) != 0o600:
                raise ValueError(f"installed profile permissions are not 0600: {name}")

        idempotent = run_installer([], codex_home)
        if idempotent.returncode != 0 or "Iguais:   " not in idempotent.stdout:
            raise ValueError(f"second isolated install was not idempotent:\n{idempotent.stdout}")

        # Exercise the documented restore operation using only temporary files.
        for installed_file in destination.glob("*.toml"):
            if installed_file.name not in original_names:
                installed_file.unlink()
        (destination / "product-lead.toml").write_bytes(
            (backup_dir / "product-lead.toml").read_bytes()
        )
        if {path.name for path in destination.glob("*.toml")} != original_names:
            raise ValueError("isolated rollback did not restore the original file set")
        if (destination / "product-lead.toml").read_bytes() != previous_profile:
            raise ValueError("isolated rollback did not restore the previous profile")

    print("Installer isolation/dry-run/idempotence/backup-restore: PASS (temporary CODEX_HOME)")


def validate_agent_eval_harness() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-eval-validation-") as temp:
        record = Path(temp) / "run.json"
        prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "prepare", "--runs", "3",
             "--profiles", str(AGENTS_DIR), "--output", str(record), "--allow-dirty"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if prepared.returncode != 0:
            raise ValueError(f"agent eval prepare failed ({prepared.returncode}):\n{prepared.stdout}")
        if "Runtime execution: NOT RUN" not in prepared.stdout:
            raise ValueError("agent eval preparation must state that it did not run agent profiles")
        data = json.loads(record.read_text(encoding="utf-8"))
        if data.get("summary", {}).get("status") != "PENDING":
            raise ValueError("new run record must start PENDING")
        if data.get("selected_case_ids") != [f"E{i}" for i in range(1, 9)]:
            raise ValueError("default eval run must cover E1–E8")
        if any(trial["status"] != "NOT RUN" for case in data["cases"] for trial in case["trials"]):
            raise ValueError("prepared eval trials must be NOT RUN")
        for case in data["cases"]:
            expected_profiles = set(case["required_profiles"])
            for trial in case["trials"]:
                observed = trial.get("observed_profiles")
                if not isinstance(observed, dict) or set(observed) != expected_profiles:
                    raise ValueError(f"{case['id']}: prepared trial must include each required profile")
                if any(item.get("identity_verified") is not False or item.get("sha256") is not None for item in observed.values()):
                    raise ValueError(f"{case['id']}: prepared profiles must start unverified with no observed hash")
        validated = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if validated.returncode != 0:
            raise ValueError(f"agent eval record validation failed ({validated.returncode}):\n{validated.stdout}")

        invalid_pass = dict(data)
        invalid_pass["summary"] = {**data["summary"], "status": "PASS"}
        first_case = dict(data["cases"][0])
        first_trial = dict(first_case["trials"][0])
        first_trial["status"] = "PASS"
        first_trial["profile_load_identity_verified"] = True
        first_case["trials"] = [first_trial, *first_case["trials"][1:]]
        invalid_pass["cases"] = [first_case, *data["cases"][1:]]
        invalid_record = Path(temp) / "invalid-pass.json"
        invalid_record.write_text(json.dumps(invalid_pass), encoding="utf-8")
        rejected = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(invalid_record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if rejected.returncode == 0 or "aggregate profile identity flag must match per-profile observations" not in rejected.stdout:
            raise ValueError("agent eval validator accepted a PASS with only an aggregate profile identity flag")

        mismatched_hash = json.loads(json.dumps(data))
        mismatched_case = mismatched_hash["cases"][0]
        mismatched_trial = mismatched_case["trials"][0]
        mismatched_trial["status"] = "PASS"
        mismatched_trial["profile_load_identity_verified"] = True
        for profile_name in mismatched_case["required_profiles"]:
            mismatched_trial["observed_profiles"][profile_name] = {
                "identity_verified": True,
                "sha256": mismatched_hash["profiles"]["sha256"][profile_name],
            }
        mismatched_trial["observed_profiles"][mismatched_case["required_profiles"][0]]["sha256"] = "f" * 64
        mismatched_record = Path(temp) / "mismatched-hash.json"
        mismatched_record.write_text(json.dumps(mismatched_hash), encoding="utf-8")
        hash_rejected = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(mismatched_record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if hash_rejected.returncode == 0 or "loaded fingerprint does not match profiles.sha256" not in hash_rejected.stdout:
            raise ValueError("agent eval validator accepted a loaded profile hash that differs from the manifest")

        subset = Path(temp) / "subset.json"
        selected = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "prepare", "--case", "E5",
             "--runs", "1", "--profiles", str(AGENTS_DIR), "--output", str(subset), "--allow-dirty"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if selected.returncode != 0:
            raise ValueError(f"agent eval subset prepare failed ({selected.returncode}):\n{selected.stdout}")
        subset_check = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(subset)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if subset_check.returncode != 0:
            raise ValueError(f"agent eval subset validation failed ({subset_check.returncode}):\n{subset_check.stdout}")
    print("Agent eval harness: PASS (8 cases × 3 pending trials; temp record; no runtime invocation)")


def main() -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11+ is required for stdlib tomllib", file=sys.stderr)
        return 2
    try:
        names = validate_profiles()
        validate_readme_manifest(names)
        validate_local_markdown_links()
        validate_installer_isolation(names)
        validate_agent_eval_harness()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"Agent package validation: FAIL\n{error}", file=sys.stderr)
        return 1
    print("Agent package validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

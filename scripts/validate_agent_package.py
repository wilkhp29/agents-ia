#!/usr/bin/env python3
"""Validate this Codex agent package and exercise installer behavior in isolation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "agents"
README = ROOT / "README.md"
INSTALLER = ROOT / "install-agents.sh"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
AGENT_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)
EGM_PIN = "0dfb5bf3eebd551d1e805c3ab16cbaa9b1c2c42a"
EGM_WRAPPERS = {
    "egm-comprehension": "comprehension",
    "egm-zoom-out": "zoom_out",
    "egm-design": "design_critic",
    "egm-structural": "structural",
    "egm-style": "style",
    "egm-implementation-readiness": "implementation_readiness",
    "egm-codebase-details": "codebase_details",
}


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


def validate_egm_wrappers() -> None:
    def validate_instruction_text(profile: str, instructions: str) -> None:
        persona = EGM_WRAPPERS[profile]
        required = (
            f"agents/{persona}.md",
            EGM_PIN,
            "BLOCKED: persona EGM não carregada",
            "AGENTS.md",
            "não criam sandbox",
            "inclusive o caminho derivado do skill ativo",
            "expected_origin=https://github.com/google/elephant-goldfish-model.git",
            "set -eu\nexpected_commit=",
            'git -C "$plugin_root" remote get-url origin',
            'git -C "$plugin_root" rev-parse --verify HEAD',
            'test "$actual_origin" = "$expected_origin"',
            'test "$actual_commit" = "$expected_commit"',
            f'git -C "$plugin_root" cat-file -e "${{expected_commit}}:agents/{persona}.md"',
            f'git -C "$plugin_root" diff --quiet "$expected_commit" -- "agents/{persona}.md"',
        )
        missing = [item for item in required if item not in instructions]
        if missing:
            raise ValueError(f"{profile} lacks required EGM identity/isolation controls: {missing}")
        proof_position = instructions.index('git -C "$plugin_root" rev-parse --verify HEAD')
        read_position = instructions.index(f"Somente depois de todos esses checks passarem, leia `agents/{persona}.md`")
        if proof_position >= read_position:
            raise ValueError(f"{profile} reads the persona before verifying the selected bundle pin")
        if "Se o caminho ativo existir mas não passar na verificação abaixo, bloqueie" not in instructions:
            raise ValueError(f"{profile} may silently fall back when the active skill path fails pin verification")
        if f'"$expected_commit:agents/{persona}.md"' in instructions:
            raise ValueError(f"{profile} uses zsh-sensitive unbraced commit interpolation before the path colon")

    for profile in EGM_WRAPPERS:
        persona = EGM_WRAPPERS[profile]
        path = AGENTS_DIR / f"{profile}.toml"
        if not path.is_file():
            raise ValueError(f"missing named EGM wrapper: {path.name}")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        instructions = data["developer_instructions"]
        validate_instruction_text(profile, instructions)
        # Regression: even if the pin-check text still exists, moving it after
        # the active-skill persona read must be rejected.
        marker = f"Somente depois de todos esses checks passarem, leia `agents/{persona}.md`"
        proof = 'git -C "$plugin_root" rev-parse --verify HEAD'
        bypass = instructions.replace(proof, "PIN_CHECK_MOVED")
        bypass = bypass.replace(marker, marker + "\n" + proof).replace("PIN_CHECK_MOVED", "")
        try:
            validate_instruction_text(profile, bypass)
        except ValueError:
            pass
        else:
            raise ValueError(f"{path.name}: validator accepted active-skill persona use before pin verification")
        # Regression: zsh treats the colon after an unbraced parameter as a
        # parameter modifier. The exact invalid form must be rejected.
        unbraced = instructions.replace(
            f'"${{expected_commit}}:agents/{persona}.md"',
            f'"$expected_commit:agents/{persona}.md"',
        )
        try:
            validate_instruction_text(profile, unbraced)
        except ValueError:
            pass
        else:
            raise ValueError(f"{path.name}: validator accepted zsh-sensitive unbraced commit interpolation")
        fail_fast_removed = instructions.replace("set -eu\nexpected_commit=", "expected_commit=", 1)
        try:
            validate_instruction_text(profile, fail_fast_removed)
        except ValueError:
            pass
        else:
            raise ValueError(f"{path.name}: validator accepted an identity-check block without fail-fast")
    for path in AGENTS_DIR.glob("egm-*.toml"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?<![A-Za-z0-9])/(?:Users|home)/", text):
            raise ValueError(f"{path.name} contains a machine-specific absolute path")
    print(f"Named EGM wrappers: PASS ({len(EGM_WRAPPERS)} persona mappings, pin and isolation caveats)")


def validate_egm_shell_commands() -> None:
    """Run checks and negative cases in bash/zsh without outer fail-fast flags."""
    shells: list[tuple[str, list[str], list[str]]] = [
        ("bash", ["bash", "--noprofile", "--norc", "-u", "-c"], ["bash", "--noprofile", "--norc", "-n", "-c"])
    ]
    zsh_path = shutil.which("zsh")
    if zsh_path:
        shells.append(("zsh", [zsh_path, "-f", "-u", "-c"], [zsh_path, "-f", "-n", "-c"]))

    with tempfile.TemporaryDirectory(prefix="egm-shell-fixture-") as temp:
        fixture = Path(temp) / "egm bundle with spaces"
        (fixture / "agents").mkdir(parents=True)
        for persona in EGM_WRAPPERS.values():
            (fixture / "agents" / f"{persona}.md").write_text(f"# {persona}\n", encoding="utf-8")
        commands = [
            ["git", "init", str(fixture)],
            ["git", "-C", str(fixture), "remote", "add", "origin", "https://github.com/google/elephant-goldfish-model.git"],
            ["git", "-C", str(fixture), "config", "user.name", "Agent package validator"],
            ["git", "-C", str(fixture), "config", "user.email", "validator@example.invalid"],
            ["git", "-C", str(fixture), "add", "agents"],
            ["git", "-C", str(fixture), "commit", "-m", "fixture"],
        ]
        for command in commands:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            if result.returncode != 0:
                raise ValueError(f"EGM shell fixture setup failed ({result.returncode}):\n{result.stdout}")
        fixture_commit = subprocess.run(
            ["git", "-C", str(fixture), "rev-parse", "HEAD"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if fixture_commit.returncode != 0:
            raise ValueError(f"cannot read EGM shell fixture commit:\n{fixture_commit.stdout}")
        fixture_commit_sha = fixture_commit.stdout.strip()

        success_origin = "https://github.com/google/elephant-goldfish-model.git"
        read_marker = "PERSONA_READ_REACHED"
        for profile, persona in EGM_WRAPPERS.items():
            data = tomllib.loads((AGENTS_DIR / f"{profile}.toml").read_text(encoding="utf-8"))
            match = re.search(r"```sh\n(.*?)\n```", data["developer_instructions"], re.DOTALL)
            if not match:
                raise ValueError(f"{profile} has no executable identity-check shell block")
            script = match.group(1).replace(EGM_PIN, fixture_commit_sha)
            script = f"plugin_root={shlex.quote(str(fixture))}\n" + script
            persona_path = fixture / "agents" / f"{persona}.md"
            for shell_name, command, syntax_command in shells:
                syntax = subprocess.run(
                    [*syntax_command, script], text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if syntax.returncode != 0:
                    raise ValueError(f"{profile} shell syntax failed in {shell_name} ({syntax.returncode}):\n{syntax.stdout}")

                # Do not pass -e to the parent shell. These assertions prove
                # that the snippet's own set -eu stops later checks and reads.
                positive = subprocess.run(
                    [*command, script + f"\nprintf '%s\\n' {shlex.quote(read_marker)}\n"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if positive.returncode != 0 or read_marker not in positive.stdout:
                    raise ValueError(f"{profile} positive control failed in {shell_name}:\n{positive.stdout}")

                # Wrong origin, but valid HEAD/persona: the initial test must
                # abort instead of allowing later successful tests to mask it.
                changed = subprocess.run(
                    ["git", "-C", str(fixture), "remote", "set-url", "origin", "https://example.invalid/wrong.git"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if changed.returncode != 0:
                    raise ValueError(f"cannot set invalid fixture origin:\n{changed.stdout}")
                invalid_origin = subprocess.run(
                    [*command, script + f"\nprintf '%s\\n' {shlex.quote(read_marker)}\n"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                restored = subprocess.run(
                    ["git", "-C", str(fixture), "remote", "set-url", "origin", success_origin],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if restored.returncode != 0:
                    raise ValueError(f"cannot restore fixture origin:\n{restored.stdout}")
                if invalid_origin.returncode == 0 or read_marker in invalid_origin.stdout:
                    raise ValueError(f"{profile} continued after invalid origin in {shell_name}:\n{invalid_origin.stdout}")

                # Wrong expected HEAD with correct origin and persona.
                wrong_sha = "0" * 40
                invalid_head_script = script.replace(f"expected_commit={fixture_commit_sha}", f"expected_commit={wrong_sha}")
                invalid_head = subprocess.run(
                    [*command, invalid_head_script + f"\nprintf '%s\\n' {shlex.quote(read_marker)}\n"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if invalid_head.returncode == 0 or read_marker in invalid_head.stdout:
                    raise ValueError(f"{profile} continued after invalid HEAD in {shell_name}:\n{invalid_head.stdout}")

                # Correct origin/HEAD, but tampered persona file; `diff` must
                # abort and prevent the persona-read marker.
                original = persona_path.read_text(encoding="utf-8")
                persona_path.write_text(original + "tampered\n", encoding="utf-8")
                invalid_persona = subprocess.run(
                    [*command, script + f"\nprintf '%s\\n' {shlex.quote(read_marker)}\n"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                persona_path.write_text(original, encoding="utf-8")
                if invalid_persona.returncode == 0 or read_marker in invalid_persona.stdout:
                    raise ValueError(f"{profile} continued after modified persona in {shell_name}:\n{invalid_persona.stdout}")

            # Reproduce the old syntax in zsh. It must fail so the test guards
            # against accidentally restoring the unbraced form.
            if zsh_path:
                old_form = (
                    f'expected_commit={fixture_commit_sha}; '
                    f'git -C {shlex.quote(str(fixture))} cat-file -e "$expected_commit:agents/{persona}.md"'
                )
                result = subprocess.run(
                    [zsh_path, "-f", "-c", old_form], text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                )
                if result.returncode == 0:
                    raise ValueError(f"{profile}: zsh unexpectedly accepted the old unbraced form")

    shell_names = ", ".join(name for name, _, _ in shells)
    if not zsh_path:
        shell_names += "; zsh unavailable, skipped"
    print(
        f"EGM shell checks: PASS ({len(EGM_WRAPPERS)} wrappers × {shell_names}; syntax, positive, "
        "invalid origin/HEAD, modified persona stop before read marker; no outer -e)"
    )


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
        serialized = json.dumps(data, ensure_ascii=False)
        if data.get("repository") != ROOT.name or data.get("profiles", {}).get("source_directory") != "workspace-agents":
            raise ValueError("run record must use portable repository/profile source identifiers")
        if str(ROOT.resolve()) in serialized or str(AGENTS_DIR.resolve()) in serialized:
            raise ValueError("run record leaked an absolute workspace or --profiles path")
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

        codex_home = Path(temp) / "codex-home"
        (codex_home / "agents").mkdir(parents=True)
        codex_record = Path(temp) / "codex-home-run.json"
        codex_env = os.environ.copy()
        codex_env["CODEX_HOME"] = str(codex_home)
        codex_prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "prepare", "--case", "E5",
             "--runs", "1", "--output", str(codex_record), "--allow-dirty"],
            cwd=ROOT, env=codex_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if codex_prepared.returncode != 0:
            raise ValueError(f"CODEX_HOME eval prepare failed ({codex_prepared.returncode}):\n{codex_prepared.stdout}")
        codex_data = json.loads(codex_record.read_text(encoding="utf-8"))
        if codex_data.get("profiles", {}).get("source_directory") != "CODEX_HOME/agents":
            raise ValueError("CODEX_HOME eval record must use a normalized profile source identifier")
        if str(codex_home.resolve()) in json.dumps(codex_data, ensure_ascii=False):
            raise ValueError("CODEX_HOME eval record leaked an absolute CODEX_HOME path")

        custom_profiles = Path(temp) / "custom-profile-dir"
        custom_record = Path(temp) / "custom-profile-run.json"
        custom_prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "prepare", "--case", "E5",
             "--runs", "1", "--profiles", str(custom_profiles), "--output", str(custom_record), "--allow-dirty"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if custom_prepared.returncode != 0:
            raise ValueError(f"custom profile eval prepare failed ({custom_prepared.returncode}):\n{custom_prepared.stdout}")
        custom_data = json.loads(custom_record.read_text(encoding="utf-8"))
        if custom_data.get("profiles", {}).get("source_directory") != "custom-directory":
            raise ValueError("custom profile eval record must use a normalized source identifier")
        if str(custom_profiles.resolve()) in json.dumps(custom_data, ensure_ascii=False):
            raise ValueError("custom profile eval record leaked the absolute --profiles path")

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

        p0_pass = json.loads(json.dumps(data))
        p0_pass["summary"]["status"] = "PASS"
        p0_pass["summary"]["hard_fail"] = False
        p0_case = next(case for case in p0_pass["cases"] if case["id"] == "E5")
        p0_trial = p0_case["trials"][0]
        p0_trial["status"] = "PASS"
        p0_trial["profile_load_identity_verified"] = True
        p0_trial["hard_fail"] = False
        for profile_name in p0_case["required_profiles"]:
            p0_trial["observed_profiles"][profile_name] = {
                "identity_verified": True,
                "sha256": p0_pass["profiles"]["sha256"][profile_name],
            }
        p0_trial["findings"] = [{
            "severity": "P0",
            "description": "unapproved external action was executed",
            "hard_fail": False,
        }]
        p0_record = Path(temp) / "p0-pass.json"
        p0_record.write_text(json.dumps(p0_pass), encoding="utf-8")
        p0_rejected = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(p0_record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if p0_rejected.returncode == 0 or "P0/P1 finding cannot be marked PASS" not in p0_rejected.stdout:
            raise ValueError("agent eval validator accepted PASS despite a P0 finding and false optional hard_fail")

        p0_summary = json.loads(json.dumps(data))
        p0_summary["summary"]["status"] = "PASS"
        p0_summary["summary"]["hard_fail"] = False
        p0_summary_trial = p0_summary["cases"][0]["trials"][0]
        p0_summary_trial["status"] = "FAIL"
        p0_summary_trial["findings"] = [{
            "severity": "p1",
            "description": "implementation started before approval",
            "hard_fail": False,
        }]
        p0_summary_record = Path(temp) / "p0-summary-pass.json"
        p0_summary_record.write_text(json.dumps(p0_summary), encoding="utf-8")
        p0_summary_rejected = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(p0_summary_record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if p0_summary_rejected.returncode == 0 or "summary must retain P0/P1 hard-fail" not in p0_summary_rejected.stdout:
            raise ValueError("agent eval validator allowed a run with normalized P1 finding to remain PASS")

        valid_pass = json.loads(json.dumps(data))
        valid_pass["git"]["dirty"] = False
        valid_pass["git"]["snapshot_reproducible"] = True
        valid_pass["runtime"] = {"name": "fixture-runtime", "version": "1", "profile_load_identity_verified": True}
        valid_pass["safety"] = {"isolated_fixture_or_worktree": True, "external_tools_mocked_fail_closed": True}
        valid_pass["repetitions_requested"] = 1
        valid_pass["summary"] = {"status": "PASS", "reviewer": "validator fixture", "hard_fail": False, "notes": []}
        evidence_bytes = b"synthetic deterministic evaluation evidence\n"
        (Path(temp) / "evidence.txt").write_bytes(evidence_bytes)
        evidence = {"uri": "evidence.txt", "sha256": hashlib.sha256(evidence_bytes).hexdigest()}
        for case in valid_pass["cases"]:
            trial = case["trials"][0]
            case["trials"] = [trial]
            trial["status"] = "PASS"
            trial["profile_load_identity_verified"] = True
            trial["evidence"] = [evidence]
            trial["deterministic_judges"] = [{
                "name": "fixture judge", "command": "python fixture judge", "exit_code": 0,
                "evidence": evidence,
            }]
            for profile_name in case["required_profiles"]:
                trial["observed_profiles"][profile_name] = {
                    "identity_verified": True,
                    "sha256": valid_pass["profiles"]["sha256"][profile_name],
                }
        valid_pass_record = Path(temp) / "valid-pass.json"
        valid_pass_record.write_text(json.dumps(valid_pass), encoding="utf-8")
        accepted = subprocess.run(
            [sys.executable, str(ROOT / "scripts/agent_eval.py"), "validate", str(valid_pass_record)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if accepted.returncode != 0:
            raise ValueError(f"agent eval validator rejected a clean PASS fixture without findings:\n{accepted.stdout}")

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
        validate_egm_wrappers()
        validate_egm_shell_commands()
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

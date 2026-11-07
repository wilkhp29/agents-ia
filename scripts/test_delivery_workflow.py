#!/usr/bin/env python3
"""Structural regression checks for the idea-to-delivery workflow contract."""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def schema_errors(value, schema, root_schema, path="$", depth=0):
    if depth > 32:
        return [f"{path}: schema nesting exceeded"]
    if "$ref" in schema:
        ref = schema["$ref"]
        target = root_schema
        if not ref.startswith("#/"):
            return [f"{path}: external ref unsupported in this fixture validator"]
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return schema_errors(value, target, root_schema, path, depth + 1)
    if "oneOf" in schema:
        branches = [schema_errors(value, branch, root_schema, path, depth + 1) for branch in schema["oneOf"]]
        return [] if sum(not errors for errors in branches) == 1 else [f"{path}: must match exactly one oneOf branch"]
    allowed_types = schema.get("type")
    if allowed_types:
        allowed_types = allowed_types if isinstance(allowed_types, list) else [allowed_types]
        matches = {
            "object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None,
        }
        if not any(matches.get(kind, False) for kind in allowed_types):
            return [f"{path}: wrong type"]
    if "const" in schema and value != schema["const"]:
        return [f"{path}: wrong const"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: outside enum"]
    errors = []
    if isinstance(value, dict):
        errors.extend(f"{path}: missing {key}" for key in schema.get("required", []) if key not in value)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}: unknown field {key}" for key in value if key not in properties)
        for key, item in value.items():
            if key in properties:
                errors.extend(schema_errors(item, properties[key], root_schema, f"{path}.{key}", depth + 1))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, schema["items"], root_schema, f"{path}[{index}]", depth + 1))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
        if len(value) > schema.get("maxLength", float("inf")):
            errors.append(f"{path}: too long")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value <= schema.get("exclusiveMinimum", float("-inf")):
            errors.append(f"{path}: below minimum")
        if value > schema.get("maximum", float("inf")) or value >= schema.get("exclusiveMaximum", float("inf")):
            errors.append(f"{path}: above maximum")
    return errors


class DeliveryWorkflowTests(unittest.TestCase):
    def test_task_envelope_example_matches_schema_required_fields(self):
        schema = json.loads((ROOT / "schemas/agent-task-envelope.schema.json").read_text())
        example = json.loads((ROOT / "docs/agent-delivery/task-envelope.example.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(schema["additionalProperties"] is False)
        self.assertTrue(set(schema["required"]) <= set(example))
        self.assertEqual(example["envelope_version"], schema["properties"]["envelope_version"]["const"])
        self.assertIsNone(example["telemetry"]["reported_total"])
        self.assertIsNone(example["telemetry"]["cost"]["reported_usd"])
        self.assertFalse(example["provenance"]["provider_model"]["identity_verified"])
        self.assertEqual(schema_errors(example, schema, schema), [])

    def test_task_envelope_rejects_unknown_fields_and_invalid_limits(self):
        schema = json.loads((ROOT / "schemas/agent-task-envelope.schema.json").read_text())
        example = json.loads((ROOT / "docs/agent-delivery/task-envelope.example.json").read_text())
        example["unapproved_field"] = "must fail"
        example["budget"]["max_calls"] = 0
        example["output_contract"]["max_chars"] = 100001
        errors = schema_errors(example, schema, schema)
        self.assertTrue(any("unknown field" in error for error in errors))
        self.assertTrue(any("below minimum" in error for error in errors))
        self.assertTrue(any("above maximum" in error for error in errors))

    def test_eval_cases_cover_idea_to_delivery_failure_modes(self):
        inventory = json.loads((ROOT / "docs/evaluations/idea-to-delivery-v1.json").read_text())
        spec = (ROOT / "docs/evaluations/idea-to-delivery-v1.md").read_text()
        ids = [case["id"] for case in inventory["cases"]]
        self.assertEqual(ids, ["D1", "D2", "D3", "D4", "D5", "D6"])
        for case in inventory["cases"]:
            self.assertIn(case["source"].split("#")[1], spec.lower())
        self.assertIn("duas rodadas", spec.lower())
        self.assertIn("identidade observada", spec.lower())
        self.assertIn("PENDING", spec)

    def test_playbook_requires_two_providers_and_bounded_refinement(self):
        playbook = (ROOT / "docs/agent-delivery/alethe-playbooks.yaml").read_text().lower()
        self.assertIn("providers: [codex, claude]", playbook)
        self.assertIn("at most 2", playbook)
        self.assertIn("cross-review", playbook)
        self.assertIn("product-qa", playbook)
        self.assertIn("budget", playbook)

    def test_code_tasks_always_reach_independent_code_review_after_build(self):
        playbook = (ROOT / "docs/agent-delivery/alethe-playbooks.yaml").read_text()
        phases = re.split(r"(?m)^      - id: ", playbook)
        phase_by_id = {
            phase.splitlines()[0].strip(): phase
            for phase in phases[1:]
        }
        self.assertIn("build", phase_by_id)
        self.assertIn("code_review", phase_by_id)
        self.assertLess(playbook.index("      - id: build"), playbook.index("      - id: code_review"))
        self.assertNotRegex(phase_by_id["code_review"], r"(?m)^        if:")
        self.assertIn("finished diff", phase_by_id["code_review"])
        self.assertIn("identity equals the writer", phase_by_id["code_review"])

    def test_parallel_task_reviews_are_independent_before_synthesis(self):
        playbook = (ROOT / "docs/agent-delivery/alethe-playbooks.yaml").read_text()
        phases = re.split(r"(?m)^      - id: ", playbook)
        phase_by_id = {
            phase.splitlines()[0].strip(): phase
            for phase in phases[1:]
        }
        claude_review = phase_by_id["task_review_claude"]
        repair = phase_by_id["task_repair"]
        self.assertIn("without relying on or reading Codex's concurrent review", claude_review)
        self.assertIn("Synthesize both independent provider review reports", repair)

    def test_product_lead_contract_references_delivery_envelope_and_gates(self):
        profile = tomllib.loads((ROOT / "agents/product-lead.toml").read_text())
        instructions = profile["developer_instructions"].lower()
        for required in (
            "briefing", "referências visuais", "viabilidade", "sdd",
            "no máximo 2 rodadas", "agent-task-envelope.schema.json", "code-reviewer", "product-qa",
        ):
            self.assertIn(required, instructions)


if __name__ == "__main__":
    unittest.main()

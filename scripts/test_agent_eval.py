import hashlib
import json
import tempfile
import unittest
from pathlib import Path

if __package__:
    from .agent_eval import (
        EVALUATIONS_DIR, ROOT, bootstrap_mean_ci, criterion_final_score,
        evaluate_size, load_rubric, load_suite, score_dimensions,
        size_score_status, validate_rubric, write_score_report,
    )
else:
    from agent_eval import (
        EVALUATIONS_DIR, ROOT, bootstrap_mean_ci, criterion_final_score,
        evaluate_size, load_rubric, load_suite, score_dimensions,
        size_score_status, validate_rubric, write_score_report,
    )


DIMENSIONS = [
    "scope_refinement",
    "technical_correctness",
    "verification_evidence",
    "safety_gates",
    "delivery_operations",
]


def sample_rubric(suite):
    cases = {}
    for case in suite["cases"]:
        criteria = []
        for index, dimension in enumerate(DIMENSIONS, start=1):
            criteria.append({
                "id": f"{case['id']}-C{index:02d}",
                "dimension": dimension,
                "weight": 1,
                "judge_type": "human",
                "source": case["source"],
                "description": f"Criterion {index} for {case['id']}",
            })
        cases[case["id"]] = {"criteria": criteria}
    return {
        "rubric": "delivery-size-v1-rubric",
        "version": 1,
        "suite": suite["suite"],
        "suite_sha256": "a" * 64,
        "dimensions": DIMENSIONS,
        "cases": cases,
        "bootstrap": {
            "method": "sha256_cluster_percentile",
            "replicates": 10000,
            "seed": "2026-11-07",
            "quantile_method": "type7",
            "confidence": 0.95,
            "minimum_holdout_scenarios": 30,
            "maximum_interval_half_width": 5.0,
            "threshold_exclusive": 85.0,
            "primary_attempts": 1,
            "reliability_repeats": "optional_preselected_stratified_subset",
            "reliability_repeat_case_ids": suite.get("reliability_repeat_case_ids", []),
            "reliability_repeats_default": suite.get("reliability_repeats_default", 0),
        },
    }


class AgentEvalScoringTests(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_constant_values_have_zero_width(self):
        first = bootstrap_mean_ci([86.0] * 30, "small")
        second = bootstrap_mean_ci([86.0] * 30, "small")
        self.assertEqual(first, second)
        self.assertEqual(first, (86.0, 86.0))

    def test_bootstrap_matches_pinned_cluster_draw_sequence(self):
        self.assertEqual(bootstrap_mean_ci([float(i) for i in range(30)], "small"), (11.5, 17.5))

    def test_bootstrap_requires_at_least_two_finite_scores(self):
        with self.assertRaises(ValueError):
            bootstrap_mean_ci([86.0], "small")
        with self.assertRaises(ValueError):
            bootstrap_mean_ci([86.0, float("nan")], "small")

    def test_reviewer_score_requires_valid_median_adjudication_on_disagreement(self):
        payload = {
            "score": 0.5,
            "reviewers": [
                {"id": "r1", "score": 0, "evidence_sufficient": True, "rationale": "evidence supports 0"},
                {"id": "r2", "score": 1, "evidence_sufficient": True, "rationale": "evidence supports 1"},
            ],
            "adjudicator": {"id": "r3", "score": 0.5, "evidence_sufficient": True, "rationale": "median adjudication"},
        }
        self.assertEqual(criterion_final_score(payload), 0.5)

    def test_reviewer_agreement_rejects_unneeded_adjudication(self):
        payload = {
            "score": 1,
            "reviewers": [
                {"id": "r1", "score": 1, "evidence_sufficient": True, "rationale": "criterion met"},
                {"id": "r2", "score": 1, "evidence_sufficient": True, "rationale": "criterion met"},
            ],
            "adjudicator": None,
        }
        self.assertEqual(criterion_final_score(payload), 1)

    def test_dimension_scores_are_equally_weighted_after_within_dimension_weights(self):
        rubric = {
            "criteria": [
                {"id": "a", "dimension": DIMENSIONS[0], "weight": 2},
                {"id": "b", "dimension": DIMENSIONS[0], "weight": 1},
                *[
                    {"id": f"c{i}", "dimension": dim, "weight": 1}
                    for i, dim in enumerate(DIMENSIONS[1:], start=2)
                ],
            ]
        }
        scores = {"a": 1, "b": 0, "c2": 1, "c3": 1, "c4": 1, "c5": 1}
        dimensions, total = score_dimensions(rubric, scores)
        self.assertAlmostEqual(dimensions[DIMENSIONS[0]], 20 * (2 / 3))
        self.assertEqual(total, sum(dimensions.values()))

    def test_threshold_requires_lower_bound_strictly_above_85_and_precision(self):
        self.assertEqual(size_score_status(85.01, 89.0, 1.995), "PASS")
        self.assertEqual(size_score_status(85.0, 89.0, 2.0), "PENDING")
        self.assertEqual(size_score_status(84.0, 90.0, 3.0), "PENDING")
        self.assertEqual(size_score_status(80.0, 85.0, 2.5), "FAIL")

    def test_rubric_requires_exact_case_coverage_and_each_dimension(self):
        suite = {
            "suite": "delivery-size-v1",
            "cases": [
                {"id": "S1", "source": "case S1"},
                {"id": "M1", "source": "case M1"},
            ],
        }
        rubric = sample_rubric(suite)
        validate_rubric(rubric, suite, "a" * 64)
        del rubric["cases"]["S1"]["criteria"][-1]
        with self.assertRaises(ValueError):
            validate_rubric(rubric, suite, "a" * 64)

    def test_committed_delivery_rubric_matches_suite_hash_and_case_map(self):
        suite_path = "docs/evaluations/delivery-size-v1.json"
        suite = load_suite(suite_path)
        digest = hashlib.sha256(Path(suite_path).read_bytes()).hexdigest()
        _, rubric, _ = load_rubric(None, suite, digest)
        self.assertEqual(set(rubric["cases"]), {case["id"] for case in suite["cases"]})

    def test_current_delivery_suite_stays_pending_without_holdout_sample(self):
        suite_path = Path("docs/evaluations/delivery-size-v1.json")
        suite = load_suite(suite_path)
        digest = hashlib.sha256(suite_path.read_bytes()).hexdigest()
        _, rubric, _ = load_rubric(None, suite, digest)
        report = evaluate_size(Path("/tmp/unused-record.json"), {}, suite, rubric, "small")
        self.assertEqual(report["status"], "PENDING")
        self.assertIn("30 are required", report["reason"])

    def _synthetic_scored_record(self, directory):
        evidence_path = Path(directory) / "evidence.txt"
        evidence_path.write_text("synthetic deterministic evidence\n", encoding="utf-8")
        evidence = {
            "uri": evidence_path.name,
            "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        }
        suite_cases = []
        rubric_cases = {}
        run_cases = []
        for index in range(30):
            case_id = f"S{index:02d}"
            source = f"synthetic-{case_id}"
            suite_cases.append({
                "id": case_id,
                "title": case_id,
                "risk": "P2",
                "source": source,
                "profiles": ["worker"],
                "size": "small",
                "partition": "holdout",
            })
            criteria = []
            criterion_scores = {}
            for criterion_index, dimension in enumerate(DIMENSIONS, start=1):
                criterion_id = f"{case_id}-C{criterion_index:02d}"
                judge_type = "deterministic" if criterion_index % 2 == 0 else "human"
                criteria.append({
                    "id": criterion_id,
                    "dimension": dimension,
                    "weight": 1,
                    "judge_type": judge_type,
                    "source": source,
                    "description": f"Synthetic criterion {criterion_id}",
                    **({"hard_fail": True} if criterion_index == 2 else {}),
                })
                result = {"score": 1, "evidence": [evidence]}
                if judge_type == "human":
                    result.update({
                        "reviewers": [
                            {"id": "reviewer-a", "score": 1, "evidence_sufficient": True, "rationale": "fixture evidence passes"},
                            {"id": "reviewer-b", "score": 1, "evidence_sufficient": True, "rationale": "fixture evidence passes"},
                        ],
                        "adjudicator": None,
                    })
                else:
                    result["judge"] = {
                        "type": "deterministic",
                        "name": "fixture-judge",
                        "command": "python check_synthetic_fixture.py",
                        "exit_code": 0,
                        "result_score": 1,
                        "evidence": evidence,
                    }
                criterion_scores[criterion_id] = result
            rubric_cases[case_id] = {"criteria": criteria}
            run_cases.append({
                "id": case_id,
                "trials": [{
                    "status": "PASS",
                    "profile_load_identity_verified": True,
                    "tokens": 100,
                    "duration_seconds": 1.0,
                    "findings": [],
                    "criterion_scores": criterion_scores,
                }],
            })
            runtime_id = f"synthetic-run-{case_id}"
            event_digest = hashlib.sha256(runtime_id.encode()).hexdigest()
            manifest_path = Path(directory) / f"{case_id}-workspace-manifest.json"
            manifest = {
                "schema_version": 1,
                "generated_by": "appserver_capture",
                "capture_event_sha256": event_digest,
                "run_id": runtime_id,
                "workspace": {
                    "root": str(Path(tempfile.gettempdir()) / f"synthetic-agent-workspace-{case_id}"),
                    "temporary": True,
                    "git_present": False,
                },
                "visible_files": [{"path": "src/main.py", "sha256": "d" * 64}],
                "excluded_paths": [
                    "docs/evaluations",
                    "docs/evaluations/delivery-size-v1.json",
                    "docs/evaluations/delivery-size-v1-rubric.json",
                ],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            capture_path = Path(directory) / f"{case_id}-capture.json"
            capture = {
                "schema_version": 1,
                "source": "codex_app_server",
                "run_id": runtime_id,
                "status": "completed",
                "runtime_version": "1",
                "duration_seconds": 1.0,
                "tokens": {"inputTokens": 40, "outputTokens": 60},
                "usage_status": "OBSERVED",
                "agent_identity_status": "OBSERVED",
                "profile_hashes_match": True,
                "profile_sha256_before": {"worker": "e" * 64},
                "profile_sha256_after": {"worker": "e" * 64},
                "threads": [{"role": "worker", "parent_thread_id": "thread_synthetic_parent"}],
                "capture_event_sha256": event_digest,
            }
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            run_cases[-1]["trials"][0].update({
                "runtime_run_id": runtime_id,
                "capture_record": {
                    "uri": capture_path.name,
                    "sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                },
                "materialized_workspace_manifest": {
                    "uri": manifest_path.name,
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                },
            })
        suite = {
            "suite": "delivery-size-v1",
            "cases": suite_cases,
            "reliability_repeat_case_ids": ["S00"],
            "reliability_repeats_default": 0,
        }
        rubric = {
            "rubric": "delivery-size-v1-rubric",
            "version": 1,
            "suite": "delivery-size-v1",
            "suite_sha256": "b" * 64,
            "dimensions": DIMENSIONS,
            "bootstrap": {
                "method": "sha256_cluster_percentile",
                "replicates": 10000,
                "seed": "2026-11-07",
                "quantile_method": "type7",
                "confidence": 0.95,
                "minimum_holdout_scenarios": 30,
                "maximum_interval_half_width": 5.0,
                "threshold_exclusive": 85.0,
                "primary_attempts": 1,
                "reliability_repeats": "optional_preselected_stratified_subset",
                "reliability_repeat_case_ids": ["S00"],
                "reliability_repeats_default": 0,
            },
            "cases": rubric_cases,
        }
        rubric_path = Path(directory) / "test-rubric.json"
        rubric_path.write_text(json.dumps(rubric), encoding="utf-8")
        record = {
            "rubric": {
                "file": rubric_path.resolve().relative_to(ROOT.resolve()).as_posix(),
                "sha256": hashlib.sha256(rubric_path.read_bytes()).hexdigest(),
            },
            "runtime": {"name": "synthetic", "version": "1", "profile_load_identity_verified": True},
            "root_instruction_source_snapshot": {
                "identity_basis": "instruction_source_snapshot",
                "root_role": "product-lead",
                "sources": {
                    "project_agents": {"before_sha256": "b" * 64, "after_sha256": "b" * 64},
                    "global_agents": {"before_sha256": "b" * 64, "after_sha256": "b" * 64},
                },
            },
            "profile_binding_config": {"before_sha256": "c" * 64, "after_sha256": "c" * 64},
            "safety": {
                "isolated_fixture_or_worktree": True,
                "external_tools_mocked_fail_closed": True,
            },
            "git": {"dirty": False, "snapshot_reproducible": True},
            "summary": {"reviewer": "reviewer-primary", "hard_fail": False},
            "repetitions_requested": 1,
            "reliability_repeat_plan": {"case_ids": [], "additional_attempts_per_case": 0},
            "cases": run_cases,
        }
        return suite, rubric, record

    def test_size_score_pass_requires_valid_full_scored_holdout_corpus(self):
        with tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
            suite, rubric, record = self._synthetic_scored_record(directory)
            report = evaluate_size(Path(directory) / "run.json", record, suite, rubric, "small")
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["mean_score"], 100)
            self.assertEqual(report["confidence_interval_95"], [100, 100])
            self.assertEqual(report["primary_trials"], 30)

    def test_preregistered_reliability_repeat_is_reported_but_not_primary_score(self):
        with tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
            suite, rubric, record = self._synthetic_scored_record(directory)
            record["reliability_repeat_plan"] = {"case_ids": ["S00"], "additional_attempts_per_case": 1}
            repeat = json.loads(json.dumps(record["cases"][0]["trials"][0]))
            repeat.update({
                "attempt": 2,
                "run_purpose": "reliability_repeat",
                "reliability_repeat_index": 1,
                "status": "FAIL",
                "tokens": 999,
            })
            record["cases"][0]["trials"].append(repeat)
            report = evaluate_size(Path(directory) / "run.json", record, suite, rubric, "small")
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["mean_score"], 100)
            self.assertEqual(report["primary_trials"], 30)
            self.assertEqual(report["reliability_repeat_trials"], 1)
            self.assertEqual(report["observed_tokens_total"], 3000)

    def test_any_p1_finding_blocks_size_score(self):
        with tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
            suite, rubric, record = self._synthetic_scored_record(directory)
            record["cases"][0]["trials"][0]["findings"] = [{"severity": "P1"}]
            report = evaluate_size(Path(directory) / "run.json", record, suite, rubric, "small")
            self.assertEqual(report["status"], "BLOCKED")

    def test_failed_hard_fail_rubric_criterion_blocks_size_score(self):
        with tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
            suite, rubric, record = self._synthetic_scored_record(directory)
            first = record["cases"][0]["trials"][0]
            hard_fail_criterion = next(
                criterion for criterion in rubric["cases"][record["cases"][0]["id"]]["criteria"]
                if criterion.get("hard_fail") is True
            )
            payload = first["criterion_scores"][hard_fail_criterion["id"]]
            payload["score"] = 0
            payload["judge"]["result_score"] = 0
            first["status"] = "FAIL"
            report = evaluate_size(Path(directory) / "run.json", record, suite, rubric, "small")
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["hard_fail_criteria"], [hard_fail_criterion["id"]])

    def test_missing_tampered_or_mismatched_capture_provenance_stays_pending(self):
        for mode in ("missing", "tampered_hash", "event_mismatch", "run_id_mismatch"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
                suite, rubric, record = self._synthetic_scored_record(directory)
                trial = record["cases"][0]["trials"][0]
                if mode == "missing":
                    trial["capture_record"] = None
                else:
                    capture_path = Path(directory) / trial["capture_record"]["uri"]
                    capture = json.loads(capture_path.read_text(encoding="utf-8"))
                    if mode == "tampered_hash":
                        capture["tokens"]["outputTokens"] += 1
                        capture_path.write_text(json.dumps(capture), encoding="utf-8")
                    else:
                        if mode == "event_mismatch":
                            capture["capture_event_sha256"] = "f" * 64
                        else:
                            capture["run_id"] = "different-runtime-run"
                        capture_path.write_text(json.dumps(capture), encoding="utf-8")
                        trial["capture_record"]["sha256"] = hashlib.sha256(capture_path.read_bytes()).hexdigest()
                report = evaluate_size(Path(directory) / "run.json", record, suite, rubric, "small")
                self.assertEqual(report["status"], "PENDING")
                self.assertIn("capture", report["reason"].lower())

    def test_score_report_is_persisted_only_inside_evaluations_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(dir=EVALUATIONS_DIR) as directory:
            output = Path(directory) / "score.json"
            report = {"results": [{"size": "small", "status": "PENDING"}]}
            self.assertEqual(write_score_report(report, output), output.resolve())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            with self.assertRaises(FileExistsError):
                write_score_report(report, output)
            with self.assertRaises(ValueError):
                write_score_report(report, Path("/tmp/score.json"))


if __name__ == "__main__":
    unittest.main()

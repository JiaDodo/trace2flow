"""End-to-end tests for the local normalized-trace CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"
DEMO_COMPILE = ROOT / "examples" / "customer-support" / "compile.json"
DEMO_HOLDOUT = ROOT / "examples" / "customer-support" / "holdout.json"
DEMO_RESOLUTION = ROOT / "examples" / "customer-support" / "resolution.json"
TAU_RESULTS = ROOT / "tests" / "fixtures" / "tau_retail_results.json"
TAU_REVIEW = ROOT / "tests" / "fixtures" / "tau_retail_review.json"
RECORDED_ROOT = ROOT / "examples" / "tau-retail-recorded"


class TraceCliTest(unittest.TestCase):
    @staticmethod
    def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "trace2flow", *args],
            cwd=ROOT,
            env=environment,
            check=check,
            capture_output=True,
            text=True,
        )

    def test_validate_reports_content_and_writes_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            output = Path(tempdir) / "normalized.json"
            result = self.run_cli("validate", str(FIXTURE), "--output", str(output))
            summary = json.loads(result.stdout)

            self.assertEqual(
                summary,
                {
                    "dataset_id": "synthetic_customer_support_m1",
                    "partition": "compile",
                    "runs": 3,
                    "steps": 18,
                    "valid": True,
                },
            )
            self.assertTrue(output.read_text(encoding="utf-8").endswith("\n"))

    def test_split_and_to_asp_write_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            root = Path(tempdir)
            compile_path = root / "compile.json"
            test_path = root / "test.json"
            asp_path = root / "compile.lp"

            split = self.run_cli(
                "split",
                str(FIXTURE),
                "--test-run-id",
                "support_run_3",
                "--compile-output",
                str(compile_path),
                "--test-output",
                str(test_path),
            )
            self.assertEqual(
                json.loads(split.stdout),
                {"compile_runs": 2, "test_runs": 1},
            )

            adapted = self.run_cli(
                "to-asp",
                str(compile_path),
                "--output",
                str(asp_path),
            )
            self.assertEqual(json.loads(adapted.stdout)["runs"], 2)
            facts = asp_path.read_text(encoding="utf-8")
            self.assertIn('job("support_run_1")', facts)
            self.assertNotIn('job("support_run_3")', facts)

    def test_tau_import_and_group_split_are_review_gated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-tau-") as tempdir:
            root = Path(tempdir)
            quarantine_path = root / "quarantine.json"
            reviewed_path = root / "reviewed.json"
            compile_path = root / "compile.json"
            test_path = root / "test.json"

            quarantined = self.run_cli(
                "import-tau",
                str(TAU_RESULTS),
                "--dataset-id",
                "tau_quarantine",
                "--task-id",
                "address-change",
                "--successful-only",
                "--output",
                str(quarantine_path),
            )
            self.assertEqual(
                json.loads(quarantined.stdout)["import_review_status"], "required"
            )
            blocked = self.run_cli(
                "mine",
                str(quarantine_path),
                "--output",
                str(root / "must_not_exist.json"),
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("require complete dependency", blocked.stderr)

            imported = self.run_cli(
                "import-tau",
                str(TAU_RESULTS),
                "--dataset-id",
                "tau_reviewed",
                "--all",
                "--review",
                str(TAU_REVIEW),
                "--output",
                str(reviewed_path),
            )
            summary = json.loads(imported.stdout)
            self.assertEqual(summary["runs"], 3)
            self.assertEqual(summary["steps"], 9)
            self.assertEqual(summary["import_review_status"], "complete")

            split = self.run_cli(
                "split",
                str(reviewed_path),
                "--test-group-id",
                "address-change-holdout",
                "--compile-output",
                str(compile_path),
                "--test-output",
                str(test_path),
            )
            self.assertEqual(
                json.loads(split.stdout), {"compile_runs": 2, "test_runs": 1}
            )

            candidate_path = root / "candidate.json"
            report_path = root / "structure-report.json"
            self.run_cli(
                "mine", str(compile_path), "--output", str(candidate_path)
            )
            evaluated = self.run_cli(
                "evaluate-structure",
                str(candidate_path),
                "--compile",
                str(compile_path),
                "--test",
                str(test_path),
                "--output",
                str(report_path),
            )
            evaluation = json.loads(evaluated.stdout)
            self.assertTrue(evaluation["all_runs_structurally_covered"])
            self.assertFalse(evaluation["execution_equivalence_claimed"])
            self.assertEqual(evaluation["validation_scope"], "held_out_structure_only")

    def test_mine_writes_evidence_bearing_candidate_dag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            output = Path(tempdir) / "candidate.json"
            result = self.run_cli("mine", str(FIXTURE), "--output", str(output))

            self.assertEqual(
                json.loads(result.stdout),
                {
                    "accepted_edges": 2,
                    "candidate_nodes": 5,
                    "source_runs": 3,
                    "unresolved_alignment_nodes": 1,
                    "unresolved_dependencies": 2,
                },
            )
            candidate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(candidate["schema_version"], "candidate-dag/1.0")
            self.assertEqual(
                candidate["upstream"]["baseline_commit"],
                "b168d6760213b489e2fb2f5571f5d4e6d648dee8",
            )
            order_node = next(
                node for node in candidate["nodes"] if node["tool"] == "lookup_order"
            )
            self.assertEqual(order_node["alignment_status"], "unresolved")
            self.assertEqual(len(order_node["occurrences"]), 6)
            self.assertTrue(
                all(len(edge["supporting_evidence"]) == 3 for edge in candidate["edges"])
            )

    def test_build_ir_keeps_undeclared_bindings_unresolved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            root = Path(tempdir)
            candidate_path = root / "candidate.json"
            workflow_path = root / "workflow.json"
            self.run_cli("mine", str(FIXTURE), "--output", str(candidate_path))
            result = self.run_cli(
                "build-ir",
                str(FIXTURE),
                "--candidate",
                str(candidate_path),
                "--output",
                str(workflow_path),
            )

            summary = json.loads(result.stdout)
            self.assertEqual(summary["nodes"], 5)
            self.assertEqual(summary["edges"], 2)
            self.assertEqual(summary["unresolved_dependencies"], 2)
            self.assertGreater(summary["blockers"], 2)
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            self.assertEqual(workflow["schema_version"], "workflow-ir/1.0")
            recommendation = next(
                node for node in workflow["nodes"] if node["tool"] == "recommend_action"
            )
            policy_binding = recommendation["parameters"]["policy_version"]
            self.assertEqual(policy_binding["kind"], "unresolved")
            self.assertIn(
                "constant",
                {candidate["kind"] for candidate in policy_binding["candidates"]},
            )

            export_path = root / "generated.py"
            exported = self.run_cli(
                "export-prefect",
                str(workflow_path),
                "--registered-tool",
                "lookup_customer",
                "--registered-tool",
                "lookup_order",
                "--registered-tool",
                "classify_issue",
                "--registered-tool",
                "recommend_action",
                "--registered-tool",
                "update_ticket",
                "--output",
                str(export_path),
                check=False,
            )
            self.assertEqual(exported.returncode, 2)
            self.assertIn("workflow is not executable", exported.stderr)
            self.assertFalse(export_path.exists())

    def test_customer_support_cli_pipeline_verifies_held_out_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-demo-") as tempdir:
            root = Path(tempdir)
            candidate_path = root / "candidate.json"
            workflow_path = root / "workflow.json"
            report_path = root / "report.json"
            self.run_cli("mine", str(DEMO_COMPILE), "--output", str(candidate_path))
            built = self.run_cli(
                "build-ir",
                str(DEMO_COMPILE),
                "--candidate",
                str(candidate_path),
                "--resolution",
                str(DEMO_RESOLUTION),
                "--output",
                str(workflow_path),
            )
            self.assertEqual(json.loads(built.stdout)["blockers"], 0)
            verified = self.run_cli(
                "verify",
                str(workflow_path),
                "--compile",
                str(DEMO_COMPILE),
                "--test",
                str(DEMO_HOLDOUT),
                "--output",
                str(report_path),
            )
            self.assertEqual(
                json.loads(verified.stdout),
                {
                    "cases": 2,
                    "passed": True,
                    "passed_cases": 2,
                    "validation_scope": "independent_local_simulation",
                },
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["synthetic_data"])
            self.assertTrue(
                all(
                    case["final_output_match"] and case["state_match"]
                    for case in report["cases"]
                )
            )

    def test_recorded_retail_cli_builds_exports_and_verifies_fresh_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-retail-") as tempdir:
            root = Path(tempdir)
            workflow_path = root / "workflow.json"
            flow_path = root / "flow.py"
            report_path = root / "report.json"
            built = self.run_cli(
                "build-ir",
                str(RECORDED_ROOT / "compile.json"),
                "--candidate",
                str(RECORDED_ROOT / "candidate.json"),
                "--resolution",
                str(RECORDED_ROOT / "resolution.json"),
                "--output",
                str(workflow_path),
            )
            self.assertEqual(json.loads(built.stdout)["blockers"], 0)

            export_args = [
                value
                for tool in (
                    "find_user_id_by_name_zip",
                    "get_order_details",
                    "get_product_details",
                    "modify_pending_order_items",
                )
                for value in ("--registered-tool", tool)
            ]
            exported = self.run_cli(
                "export-prefect",
                str(workflow_path),
                *export_args,
                "--output",
                str(flow_path),
            )
            self.assertEqual(len(json.loads(exported.stdout)["required_tools"]), 4)
            self.assertIn("ToolRegistry", flow_path.read_text(encoding="utf-8"))

            verified = self.run_cli(
                "verify-retail",
                str(workflow_path),
                "--cases",
                str(RECORDED_ROOT / "execution-cases.json"),
                "--output",
                str(report_path),
            )
            self.assertEqual(
                json.loads(verified.stdout),
                {
                    "cases": 2,
                    "passed": True,
                    "passed_cases": 2,
                    "recorded_response_replay_used": False,
                    "validation_scope": (
                        "independent_local_simulation_of_recorded_structure"
                    ),
                },
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["recorded_structure_source"])
            self.assertTrue(all(case["state_match"] for case in report["cases"]))


if __name__ == "__main__":
    unittest.main()

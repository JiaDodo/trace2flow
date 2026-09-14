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


class TraceCliTest(unittest.TestCase):
    @staticmethod
    def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "trace2flow", *args],
            cwd=ROOT,
            env=environment,
            check=True,
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


if __name__ == "__main__":
    unittest.main()

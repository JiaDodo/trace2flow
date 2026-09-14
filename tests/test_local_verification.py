"""End-to-end held-out verification in the independent local simulator."""

from __future__ import annotations

import ast
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.candidate import mine_candidate_dag
from trace2flow.datasets import DatasetLeakageError
from trace2flow.io import load_trace_dataset
from trace2flow.ir import ResolutionPlan, build_workflow_ir
from trace2flow.models import TraceDataset
from trace2flow.simulation import replay_structure, verify_workflow

COMPILE = ROOT / "examples" / "customer-support" / "compile.json"
HOLDOUT = ROOT / "examples" / "customer-support" / "holdout.json"
RESOLUTION = ROOT / "examples" / "customer-support" / "resolution.json"


def resolved_demo():
    compile_dataset = load_trace_dataset(COMPILE)
    test_dataset = load_trace_dataset(HOLDOUT)
    candidate = mine_candidate_dag(compile_dataset)
    resolution = ResolutionPlan.model_validate_json(
        RESOLUTION.read_text(encoding="utf-8")
    )
    workflow = build_workflow_ir(compile_dataset, candidate, resolution)
    return compile_dataset, test_dataset, candidate, workflow


class LocalVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.compile_dataset,
            cls.test_dataset,
            cls.candidate,
            cls.workflow,
        ) = resolved_demo()

    def test_demo_compiles_to_fully_resolved_five_tool_workflow(self) -> None:
        self.assertEqual(len(self.compile_dataset.runs), 3)
        self.assertEqual(len(self.test_dataset.runs), 2)
        self.assertEqual(len(self.candidate.nodes), 5)
        self.assertEqual(len(self.candidate.edges), 5)
        self.assertEqual(self.candidate.unresolved_dependencies, [])
        self.assertEqual(self.workflow.execution_blockers(), [])
        self.assertEqual(
            {node.tool for node in self.workflow.nodes},
            {
                "lookup_customer",
                "lookup_order",
                "classify_issue",
                "recommend_action",
                "update_ticket",
            },
        )

    def test_recorded_replay_is_explicitly_partial(self) -> None:
        results = [
            replay_structure(self.workflow, run) for run in self.test_dataset.runs
        ]
        self.assertTrue(all(item.tools_present for item in results))
        self.assertTrue(all(item.dependencies_present for item in results))
        self.assertTrue(
            all(
                item.validation_scope == "recorded_response_replay_partial"
                and not item.equivalent_execution_claimed
                for item in results
            )
        )

    def test_independent_simulation_matches_outputs_and_state_changes(self) -> None:
        report = verify_workflow(
            self.workflow,
            self.compile_dataset,
            self.test_dataset,
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.validation_scope, "independent_local_simulation")
        self.assertTrue(report.synthetic_data)
        self.assertEqual([case.status for case in report.cases], ["passed", "passed"])
        self.assertTrue(all(case.final_output_match for case in report.cases))
        self.assertTrue(all(case.state_match for case in report.cases))
        self.assertTrue(
            all(case.actual_changes == case.expected_changes for case in report.cases)
        )
        self.assertEqual(
            {case.actual_final_output["recommendation"] for case in report.cases},
            {"carrier_investigation", "replacement_offer"},
        )

    def test_intentional_expected_mismatch_fails_both_checks(self) -> None:
        payload = copy.deepcopy(self.test_dataset.model_dump(mode="json"))
        payload["runs"] = [payload["runs"][0]]
        payload["runs"][0]["final_output"]["status"] = "incorrect_expected_status"
        payload["runs"][0]["state_after"]["tickets"]["T-101"]["status"] = (
            "incorrect_expected_status"
        )
        mismatched = TraceDataset.model_validate(payload)

        report = verify_workflow(self.workflow, self.compile_dataset, mismatched)

        self.assertFalse(report.passed)
        self.assertEqual(report.cases[0].status, "failed")
        self.assertFalse(report.cases[0].final_output_match)
        self.assertFalse(report.cases[0].state_match)
        self.assertNotEqual(
            report.cases[0].actual_changes,
            report.cases[0].expected_changes,
        )

    def test_verification_rejects_compile_test_provenance_leakage(self) -> None:
        payload = self.test_dataset.model_dump(mode="json")
        payload["runs"][0]["provenance"] = self.compile_dataset.runs[
            0
        ].provenance.model_dump(mode="json")
        leaked = TraceDataset.model_validate(payload)

        with self.assertRaises(DatasetLeakageError):
            verify_workflow(self.workflow, self.compile_dataset, leaked)

    def test_simulator_source_has_no_network_or_refund_dispatch(self) -> None:
        source = (ROOT / "src" / "trace2flow" / "simulation.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        self.assertTrue(
            {"requests", "httpx", "socket", "urllib"}.isdisjoint(imported_roots)
        )
        self.assertNotIn("issue_refund", source)
        self.assertNotIn("send_message", source)


if __name__ == "__main__":
    unittest.main()

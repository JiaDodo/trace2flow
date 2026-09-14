"""Recorded-structure binding and independent retail execution regression tests."""

from __future__ import annotations

import ast
import copy
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.candidate import CandidateDag
from trace2flow.io import load_trace_dataset
from trace2flow.ir import ResolutionPlan, TaskInputBinding, build_workflow_ir
from trace2flow.prefect_export import export_prefect
from trace2flow.retail_simulation import (
    RETAIL_TOOLS,
    RetailSimulationSuite,
    RetailSimulator,
    load_retail_suite,
    verify_retail_workflow,
)

RECORDED = ROOT / "examples" / "tau-retail-recorded"


def recorded_workflow():
    compile_dataset = load_trace_dataset(RECORDED / "compile.json")
    candidate = CandidateDag.model_validate_json(
        (RECORDED / "candidate.json").read_text(encoding="utf-8")
    )
    resolution = ResolutionPlan.model_validate_json(
        (RECORDED / "resolution.json").read_text(encoding="utf-8")
    )
    return build_workflow_ir(compile_dataset, candidate, resolution)


class RecordedRetailExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = recorded_workflow()
        cls.suite = load_retail_suite(RECORDED / "execution-cases.json")

    def test_recorded_workflow_uses_explicit_contract_not_constants(self) -> None:
        self.assertEqual(self.workflow.execution_blockers(), [])
        self.assertEqual(self.workflow.output_node_ids, ["node_b5265cf2e501"])
        self.assertEqual({node.tool for node in self.workflow.nodes}, RETAIL_TOOLS)
        bindings = [
            binding
            for node in self.workflow.nodes
            for binding in node.parameters.values()
        ]
        self.assertEqual(len(bindings), 9)
        self.assertTrue(all(isinstance(binding, TaskInputBinding) for binding in bindings))
        self.assertTrue(
            all(
                binding.evidence_mode == "declared_runtime_contract"
                and all(
                    evidence.validation == "declared_runtime_contract"
                    for evidence in binding.evidence
                )
                for binding in bindings
                if isinstance(binding, TaskInputBinding)
            )
        )

    def test_fresh_cases_match_business_output_and_complete_order_state(self) -> None:
        report = verify_retail_workflow(self.workflow, self.suite)

        self.assertTrue(report.passed)
        self.assertTrue(report.recorded_structure_source)
        self.assertFalse(report.recorded_response_replay_used)
        self.assertEqual(
            report.validation_scope,
            "independent_local_simulation_of_recorded_structure",
        )
        self.assertEqual([case.status for case in report.cases], ["passed", "passed"])
        self.assertTrue(all(case.final_output_match for case in report.cases))
        self.assertTrue(all(case.state_match for case in report.cases))
        self.assertTrue(
            all(case.expected_changes == case.actual_changes for case in report.cases)
        )
        self.assertEqual(
            self.suite.cases[0].initial_state.orders["LOCAL-O-UNCHANGED"],
            self.suite.cases[0].expected_orders_after["LOCAL-O-UNCHANGED"],
        )

    def test_output_and_state_corruption_fail_independently(self) -> None:
        output_payload = copy.deepcopy(self.suite.model_dump(mode="json"))
        output_payload["cases"] = [output_payload["cases"][0]]
        output_payload["cases"][0]["expected_final_output"]["status"] = "corrupt"
        output_report = verify_retail_workflow(
            self.workflow,
            RetailSimulationSuite.model_validate(output_payload),
        )
        self.assertFalse(output_report.passed)
        self.assertFalse(output_report.cases[0].final_output_match)
        self.assertTrue(output_report.cases[0].state_match)

        state_payload = copy.deepcopy(self.suite.model_dump(mode="json"))
        state_payload["cases"] = [state_payload["cases"][0]]
        state_payload["cases"][0]["expected_orders_after"]["LOCAL-O-101"][
            "status"
        ] = "corrupt"
        state_report = verify_retail_workflow(
            self.workflow,
            RetailSimulationSuite.model_validate(state_payload),
        )
        self.assertFalse(state_report.passed)
        self.assertTrue(state_report.cases[0].final_output_match)
        self.assertFalse(state_report.cases[0].state_match)

    def test_inconsistent_product_input_fails_before_order_mutation(self) -> None:
        payload = copy.deepcopy(self.suite.model_dump(mode="json"))
        payload["cases"] = [payload["cases"][0]]
        payload["cases"][0]["task_input"]["product_id"] = "LOCAL-P-UNKNOWN"
        report = verify_retail_workflow(
            self.workflow,
            RetailSimulationSuite.model_validate(payload),
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.cases[0].status, "error")
        self.assertIn("unknown local product", report.cases[0].error)
        self.assertEqual(report.cases[0].actual_changes, [])

    def test_generated_prefect_flow_dispatches_only_registered_local_tools(self) -> None:
        artifact = export_prefect(self.workflow, RETAIL_TOOLS)
        self.assertEqual(set(artifact.required_tools), RETAIL_TOOLS)
        case = self.suite.cases[0]
        simulator = RetailSimulator.for_state(case.initial_state)
        with tempfile.TemporaryDirectory(prefix="trace2flow-retail-prefect-") as tempdir:
            generated = Path(tempdir) / "generated_flow.py"
            artifact.write(generated)
            spec = importlib.util.spec_from_file_location("recorded_retail_flow", generated)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            previous_level = os.environ.get("PREFECT_LOGGING_LEVEL")
            os.environ["PREFECT_LOGGING_LEVEL"] = "ERROR"
            try:
                result = module.run_workflow(case.task_input, simulator.registry())
            finally:
                if previous_level is None:
                    os.environ.pop("PREFECT_LOGGING_LEVEL", None)
                else:
                    os.environ["PREFECT_LOGGING_LEVEL"] = previous_level

        self.assertEqual(result["final_output"], case.expected_final_output)
        self.assertEqual(simulator.orders, case.expected_orders_after)

    def test_fixtures_are_fresh_and_simulator_has_no_external_dispatch(self) -> None:
        fixture_text = (RECORDED / "execution-cases.json").read_text(encoding="utf-8")
        self.assertNotIn("<user_id_", fixture_text)
        self.assertNotIn("<order_id_", fixture_text)
        self.assertIn('"recorded_response_replay": false', fixture_text)

        source = (ROOT / "src" / "trace2flow" / "retail_simulation.py").read_text(
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

"""Safety gates and real local execution for generated Prefect flows."""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.ir import WorkflowIR
from trace2flow.prefect_export import PrefectExportError, export_prefect
from trace2flow.runtime import ToolRegistry, UnregisteredToolError


def executable_workflow() -> WorkflowIR:
    make_occurrence = {
        "run_id": "compile_1",
        "step_id": "make_1",
        "qualified_id": "compile_1:make_1",
    }
    multiply_occurrence = {
        "run_id": "compile_1",
        "step_id": "multiply_1",
        "qualified_id": "compile_1:multiply_1",
    }
    edge_evidence = {
        "run_id": "compile_1",
        "source_occurrence_id": "compile_1:make_1",
        "target_occurrence_id": "compile_1:multiply_1",
        "declaration": "depends_on",
    }
    return WorkflowIR.model_validate(
        {
            "schema_version": "workflow-ir/1.0",
            "workflow_id": "synthetic-prefect-smoke",
            "source_dataset_id": "synthetic-prefect-compile",
            "source_sha256": "0" * 64,
            "candidate_schema_version": "candidate-dag/1.0",
            "nodes": [
                {
                    "id": "make",
                    "tool": "make_value",
                    "occurrences": [make_occurrence],
                    "parameters": {
                        "x": {
                            "kind": "task_input",
                            "path": ["x"],
                            "declared": True,
                            "rationale": "explicit_declaration",
                            "evidence": [
                                {
                                    "run_id": "compile_1",
                                    "target_occurrence_id": "compile_1:make_1",
                                    "source_kind": "task_input",
                                    "source_path": ["x"],
                                    "source_occurrence_id": None,
                                    "observed_value": 3,
                                }
                            ],
                        }
                    },
                    "side_effects": [{"kind": "none"}],
                    "alignment_status": "aligned",
                    "branch_resolution": "resolved",
                    "branch_reason": None,
                    "side_effect_resolution": "resolved",
                    "side_effect_reason": None,
                },
                {
                    "id": "multiply",
                    "tool": "multiply_value",
                    "occurrences": [multiply_occurrence],
                    "parameters": {
                        "value": {
                            "kind": "tool_output",
                            "source_node_id": "make",
                            "path": ["value"],
                            "declared": True,
                            "rationale": "explicit_declaration",
                            "evidence": [
                                {
                                    "run_id": "compile_1",
                                    "target_occurrence_id": "compile_1:multiply_1",
                                    "source_kind": "tool_output",
                                    "source_path": ["value"],
                                    "source_occurrence_id": "compile_1:make_1",
                                    "observed_value": 3,
                                }
                            ],
                        },
                        "factor": {
                            "kind": "constant",
                            "value": 2,
                            "declared": True,
                            "rationale": "explicit_declaration",
                            "evidence": [
                                {
                                    "run_id": "compile_1",
                                    "target_occurrence_id": "compile_1:multiply_1",
                                    "source_kind": "constant",
                                    "source_path": [],
                                    "source_occurrence_id": None,
                                    "observed_value": 2,
                                }
                            ],
                        },
                    },
                    "side_effects": [{"kind": "none"}],
                    "alignment_status": "aligned",
                    "branch_resolution": "resolved",
                    "branch_reason": None,
                    "side_effect_resolution": "resolved",
                    "side_effect_reason": None,
                },
            ],
            "edges": [
                {
                    "id": "make-to-multiply",
                    "source_node_id": "make",
                    "target_node_id": "multiply",
                    "evidence": [edge_evidence],
                    "rationale": "explicit_depends_on",
                }
            ],
            "unresolved_dependencies": 0,
        }
    )


class PrefectExportTest(unittest.TestCase):
    def test_generated_source_is_static_and_runs_in_real_prefect(self) -> None:
        workflow = executable_workflow()
        artifact = export_prefect(
            workflow,
            {"make_value", "multiply_value"},
        )
        tree = ast.parse(artifact.source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(imported, {"__future__", "prefect", "trace2flow.runtime"})
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue({"flow", "task", "_invoke_registered"} <= called_names)
        self.assertTrue({"eval", "exec", "compile", "__import__"}.isdisjoint(called_names))

        calls: list[tuple[str, dict[str, object]]] = []

        def make_value(**params):
            calls.append(("make_value", params))
            return {"value": params["x"]}

        def multiply_value(**params):
            calls.append(("multiply_value", params))
            return {"result": params["value"] * params["factor"]}

        registry = ToolRegistry(
            {"make_value": make_value, "multiply_value": multiply_value}
        )
        with tempfile.TemporaryDirectory(prefix="trace2flow-prefect-") as tempdir:
            generated = Path(tempdir) / "generated_flow.py"
            artifact.write(generated)
            spec = importlib.util.spec_from_file_location("generated_flow", generated)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            previous_level = os.environ.get("PREFECT_LOGGING_LEVEL")
            os.environ["PREFECT_LOGGING_LEVEL"] = "ERROR"
            try:
                result = module.run_workflow({"x": 4}, registry)
            finally:
                if previous_level is None:
                    os.environ.pop("PREFECT_LOGGING_LEVEL", None)
                else:
                    os.environ["PREFECT_LOGGING_LEVEL"] = previous_level

        self.assertEqual(result["final_output"], {"result": 8})
        self.assertEqual(
            calls,
            [
                ("make_value", {"x": 4}),
                ("multiply_value", {"factor": 2, "value": 4}),
            ],
        )

    def test_unresolved_workflow_is_rejected_with_parameter_location(self) -> None:
        payload = executable_workflow().model_dump(mode="json")
        payload["nodes"][1]["parameters"]["factor"] = {
            "kind": "unresolved",
            "reason": "not declared",
            "observed_values": [2],
            "candidates": [],
        }
        workflow = WorkflowIR.model_validate(payload)

        with self.assertRaisesRegex(
            PrefectExportError,
            r"parameter multiply\.factor is unresolved",
        ):
            export_prefect(workflow, {"make_value", "multiply_value"})

    def test_export_and_runtime_both_reject_unregistered_tools(self) -> None:
        workflow = executable_workflow()
        with self.assertRaisesRegex(PrefectExportError, "multiply_value"):
            export_prefect(workflow, {"make_value"})

        calls: list[str] = []
        registry = ToolRegistry({"make_value": lambda **_: calls.append("called")})
        with self.assertRaisesRegex(UnregisteredToolError, "not registered"):
            registry.invoke("multiply_value", {"value": 2})
        self.assertEqual(calls, [])

    def test_trace_strings_are_emitted_only_as_literals(self) -> None:
        payload = executable_workflow().model_dump(mode="json")
        malicious = "__import__('os').system('should_not_run')"
        payload["nodes"][1]["parameters"]["factor"]["value"] = malicious
        payload["nodes"][1]["parameters"]["factor"]["evidence"][0][
            "observed_value"
        ] = malicious
        workflow = WorkflowIR.model_validate(payload)
        artifact = export_prefect(workflow, {"make_value", "multiply_value"})

        tree = ast.parse(artifact.source)
        self.assertIn(malicious, {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)})
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                for node in ast.walk(tree)
            )
        )


if __name__ == "__main__":
    unittest.main()

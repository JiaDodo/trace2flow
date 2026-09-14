"""Tests for Workflow IR validation and declaration-gated parameter binding."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.asp import to_asp
from trace2flow.candidate import build_candidate_dag
from trace2flow.ir import (
    BindingOverride,
    ConstantBinding,
    ConstantBindingSpec,
    ResolutionPlan,
    ResolutionStatus,
    TaskInputBinding,
    TaskInputBindingSpec,
    ToolOutputBinding,
    ToolOutputBindingSpec,
    UnresolvedBinding,
    WorkflowIR,
    build_workflow_ir,
    loads_workflow_ir,
    workflow_ir_json,
)
from trace2flow.models import TraceDataset
from trace2flow.upstream import RuleProfile, UpstreamConditional, UpstreamSignals


def binding_dataset() -> TraceDataset:
    runs = []
    for number, customer_id in ((1, "C-001"), (2, "C-002")):
        runs.append(
            {
                "id": f"run_{number}",
                "provenance": {
                    "kind": "synthetic",
                    "source": "workflow-ir-test",
                    "source_run_id": f"case_{number}",
                },
                "inputs": {
                    "customer_id": customer_id,
                    "priority": 1,
                    "flag": False,
                },
                "steps": [
                    {
                        "id": f"lookup_{number}",
                        "tool": "lookup_customer",
                        "params": {
                            "customer_id": customer_id,
                            "include_inactive": False,
                        },
                        "output": {"id": customer_id, "active": False},
                        "status": "completed",
                        "side_effects": [
                            {"kind": "read", "target": "mock.customers"}
                        ],
                    },
                    {
                        "id": f"classify_{number}",
                        "tool": "classify_issue",
                        "params": {
                            "customer_id": customer_id,
                            "priority": 1,
                            "active": False,
                        },
                        "output": {"category": "account"},
                        "depends_on": [f"lookup_{number}"],
                        "status": "completed",
                        "side_effects": [{"kind": "none"}],
                    },
                ],
                "status": "completed",
            }
        )
    return TraceDataset.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "synthetic_workflow_ir",
            "partition": "compile",
            "runs": runs,
            "metadata": {"synthetic": True},
        }
    )


def upstream_signals(dataset: TraceDataset) -> UpstreamSignals:
    return UpstreamSignals(
        source_sha256=to_asp(dataset).source_sha256,
        rules_sha256="0" * 64,
        compiler_sha256="1" * 64,
        rule_profile=RuleProfile.STRICT,
        source_runs=2,
        compiled_call_count=2,
        core_tools=["lookup_customer", "classify_issue"],
        phases={0: ["lookup_customer"], 1: ["classify_issue"]},
        conditionals=[],
        fusion_candidates=[],
        mutually_exclusive=[],
        conflicting_order_choices=[],
        variable_params={},
    )


def candidate_and_ids():
    dataset = binding_dataset()
    candidate = build_candidate_dag(dataset, upstream_signals(dataset))
    node_ids = {node.tool: node.id for node in candidate.nodes}
    return dataset, candidate, node_ids


class WorkflowIrTest(unittest.TestCase):
    def test_equality_and_invariance_remain_unresolved_candidates(self) -> None:
        dataset, candidate, node_ids = candidate_and_ids()
        workflow = build_workflow_ir(dataset, candidate)
        nodes = {node.tool: node for node in workflow.nodes}

        customer_binding = nodes["classify_issue"].parameters["customer_id"]
        self.assertIsInstance(customer_binding, UnresolvedBinding)
        self.assertEqual(
            {item.kind for item in customer_binding.candidates},
            {"task_input", "tool_output"},
        )
        output_candidate = next(
            item for item in customer_binding.candidates if item.kind == "tool_output"
        )
        self.assertEqual(output_candidate.source_node_id, node_ids["lookup_customer"])
        self.assertEqual(output_candidate.path, ["id"])

        common_binding = nodes["classify_issue"].parameters["active"]
        self.assertIsInstance(common_binding, UnresolvedBinding)
        self.assertEqual(
            {item.kind for item in common_binding.candidates},
            {"constant", "task_input", "tool_output"},
        )
        self.assertIn(
            f"parameter {node_ids['classify_issue']}.active is unresolved",
            workflow.execution_blockers(),
        )

    def test_explicit_declarations_create_typed_resolved_bindings(self) -> None:
        dataset, candidate, node_ids = candidate_and_ids()
        lookup_id = node_ids["lookup_customer"]
        classify_id = node_ids["classify_issue"]
        plan = ResolutionPlan(
            binding_overrides=[
                BindingOverride(
                    node_id=lookup_id,
                    parameter="customer_id",
                    binding=TaskInputBindingSpec(path=["customer_id"]),
                ),
                BindingOverride(
                    node_id=lookup_id,
                    parameter="include_inactive",
                    binding=ConstantBindingSpec(value=False),
                ),
                BindingOverride(
                    node_id=classify_id,
                    parameter="customer_id",
                    binding=ToolOutputBindingSpec(
                        source_node_id=lookup_id,
                        path=["id"],
                    ),
                ),
                BindingOverride(
                    node_id=classify_id,
                    parameter="priority",
                    binding=TaskInputBindingSpec(path=["priority"]),
                ),
                BindingOverride(
                    node_id=classify_id,
                    parameter="active",
                    binding=ToolOutputBindingSpec(
                        source_node_id=lookup_id,
                        path=["active"],
                    ),
                ),
            ]
        )
        workflow = build_workflow_ir(dataset, candidate, plan)
        nodes = {node.tool: node for node in workflow.nodes}

        self.assertIsInstance(
            nodes["lookup_customer"].parameters["customer_id"], TaskInputBinding
        )
        constant = nodes["lookup_customer"].parameters["include_inactive"]
        self.assertIsInstance(constant, ConstantBinding)
        self.assertIs(type(constant.value), bool)
        self.assertFalse(constant.value)
        output = nodes["classify_issue"].parameters["active"]
        self.assertIsInstance(output, ToolOutputBinding)
        self.assertEqual(output.path, ["active"])
        self.assertEqual(workflow.execution_blockers(), [])

        restored = loads_workflow_ir(workflow_ir_json(workflow))
        restored_constant = next(
            node for node in restored.nodes if node.tool == "lookup_customer"
        ).parameters["include_inactive"]
        self.assertIsInstance(restored_constant, ConstantBinding)
        self.assertIs(type(restored_constant.value), bool)
        self.assertEqual(restored, workflow)

    def test_contradictory_constant_declaration_is_rejected(self) -> None:
        dataset, candidate, node_ids = candidate_and_ids()
        plan = ResolutionPlan(
            binding_overrides=[
                BindingOverride(
                    node_id=node_ids["lookup_customer"],
                    parameter="include_inactive",
                    binding=ConstantBindingSpec(value=True),
                )
            ]
        )

        with self.assertRaisesRegex(ValueError, "contradicts observations"):
            build_workflow_ir(dataset, candidate, plan)

    def test_output_binding_requires_an_accepted_dependency_edge(self) -> None:
        dataset, candidate, node_ids = candidate_and_ids()
        plan = ResolutionPlan(
            binding_overrides=[
                BindingOverride(
                    node_id=node_ids["lookup_customer"],
                    parameter="customer_id",
                    binding=ToolOutputBindingSpec(
                        source_node_id=node_ids["classify_issue"],
                        path=["category"],
                    ),
                )
            ]
        )

        with self.assertRaisesRegex(ValueError, "lacks an accepted edge"):
            build_workflow_ir(dataset, candidate, plan)

    def test_workflow_model_rejects_cycles_and_invalid_references(self) -> None:
        dataset, candidate, _ = candidate_and_ids()
        workflow = build_workflow_ir(dataset, candidate)
        payload = workflow.model_dump(mode="json")
        original = payload["edges"][0]
        payload["edges"].append(
            {
                "id": "reverse",
                "source_node_id": original["target_node_id"],
                "target_node_id": original["source_node_id"],
                "evidence": original["evidence"],
                "rationale": "explicit_depends_on",
            }
        )
        with self.assertRaisesRegex(ValidationError, "must form a DAG"):
            WorkflowIR.model_validate(payload)

        payload = workflow.model_dump(mode="json")
        payload["edges"][0]["source_node_id"] = "missing_node"
        with self.assertRaisesRegex(ValidationError, "unknown node"):
            WorkflowIR.model_validate(payload)

    def test_branch_and_write_side_effect_require_confirmation(self) -> None:
        dataset = binding_dataset()
        payload = dataset.model_dump(mode="json")
        for run in payload["runs"]:
            run["steps"][1]["side_effects"] = [
                {"kind": "write", "target": "mock.tickets", "reversible": True}
            ]
        dataset = TraceDataset.model_validate(payload)
        signals = upstream_signals(dataset).model_copy(
            update={
                "conditionals": [
                    UpstreamConditional(
                        tool="classify_issue",
                        depends_on="lookup_customer",
                        rate="1/2",
                    )
                ]
            }
        )
        candidate = build_candidate_dag(dataset, signals)
        target_id = next(
            node.id for node in candidate.nodes if node.tool == "classify_issue"
        )

        unresolved = next(
            node
            for node in build_workflow_ir(dataset, candidate).nodes
            if node.id == target_id
        )
        self.assertEqual(unresolved.branch_resolution, ResolutionStatus.UNRESOLVED)
        self.assertEqual(
            unresolved.side_effect_resolution,
            ResolutionStatus.UNRESOLVED,
        )

        confirmed = next(
            node
            for node in build_workflow_ir(
                dataset,
                candidate,
                ResolutionPlan(
                    confirmed_branch_nodes=[target_id],
                    confirmed_side_effect_nodes=[target_id],
                ),
            ).nodes
            if node.id == target_id
        )
        self.assertEqual(confirmed.branch_resolution, ResolutionStatus.RESOLVED)
        self.assertEqual(confirmed.side_effect_resolution, ResolutionStatus.RESOLVED)


if __name__ == "__main__":
    unittest.main()

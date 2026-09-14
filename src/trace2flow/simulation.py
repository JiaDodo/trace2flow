"""Independent local customer-support simulation and outcome verification."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from .datasets import assert_disjoint
from .io import canonical_json
from .ir import (
    ConstantBinding,
    TaskInputBinding,
    ToolOutputBinding,
    WorkflowIR,
)
from .models import DatasetPartition, StrictModel, TraceDataset, TraceRun
from .runtime import ToolRegistry, get_path


class WorkflowExecutionError(RuntimeError):
    """A local workflow could not execute safely."""


class StateChange(StrictModel):
    operation: Literal["add", "remove", "replace"]
    path: list[str | int]
    before: JsonValue = None
    after: JsonValue = None


class ExecutionResult(StrictModel):
    workflow_id: str
    outputs: dict[str, JsonValue]
    final_output: JsonValue


class ReplayStructureResult(StrictModel):
    validation_scope: Literal["recorded_response_replay_partial"] = (
        "recorded_response_replay_partial"
    )
    equivalent_execution_claimed: Literal[False] = False
    tools_present: bool
    dependencies_present: bool


class VerificationCaseResult(StrictModel):
    run_id: str
    status: Literal["passed", "failed", "error"]
    final_output_match: bool
    state_match: bool
    expected_final_output: JsonValue
    actual_final_output: JsonValue = None
    expected_changes: list[StateChange]
    actual_changes: list[StateChange]
    error: str | None = None


class VerificationReport(StrictModel):
    schema_version: Literal["verification-report/1.0"] = "verification-report/1.0"
    validation_scope: Literal["independent_local_simulation"] = (
        "independent_local_simulation"
    )
    synthetic_data: Literal[True] = True
    compile_dataset_id: str
    test_dataset_id: str
    workflow_id: str
    cases: list[VerificationCaseResult]
    passed: bool


def verification_report_json(report: VerificationReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _token(value: JsonValue) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def state_diff(before: JsonValue, after: JsonValue) -> list[StateChange]:
    """Return a deterministic structural diff suitable for exact comparison."""

    changes: list[StateChange] = []

    def compare(left: JsonValue, right: JsonValue, path: list[str | int]) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() - right.keys()):
                changes.append(
                    StateChange(operation="remove", path=[*path, key], before=left[key])
                )
            for key in sorted(right.keys() - left.keys()):
                changes.append(
                    StateChange(operation="add", path=[*path, key], after=right[key])
                )
            for key in sorted(left.keys() & right.keys()):
                compare(left[key], right[key], [*path, key])
            return
        if _token(left) != _token(right):
            changes.append(
                StateChange(operation="replace", path=path, before=left, after=right)
            )

    compare(before, after, [])
    return changes


def _topological_node_ids(workflow: WorkflowIR) -> list[str]:
    predecessors = {node.id: set() for node in workflow.nodes}
    for edge in workflow.edges:
        predecessors[edge.target_node_id].add(edge.source_node_id)
    remaining = set(predecessors)
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            node_id
            for node_id in remaining
            if predecessors[node_id].isdisjoint(remaining)
        )
        if not ready:
            raise WorkflowExecutionError("workflow contains a cycle")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def execute_local(
    workflow: WorkflowIR,
    task_input: dict[str, JsonValue],
    registry: ToolRegistry,
) -> ExecutionResult:
    """Execute resolved bindings using only explicitly registered callables."""

    blockers = workflow.execution_blockers()
    if blockers:
        raise WorkflowExecutionError(
            "workflow is not executable:\n- " + "\n- ".join(blockers)
        )
    required_tools = {node.tool for node in workflow.nodes}
    missing_tools = sorted(required_tools - registry.names)
    if missing_tools:
        raise WorkflowExecutionError(
            "missing registered tool(s): " + ", ".join(missing_tools)
        )
    nodes = {node.id: node for node in workflow.nodes}
    outputs: dict[str, JsonValue] = {}
    for node_id in _topological_node_ids(workflow):
        node = nodes[node_id]
        params: dict[str, JsonValue] = {}
        for name, binding in node.parameters.items():
            if isinstance(binding, ConstantBinding):
                params[name] = copy.deepcopy(binding.value)
            elif isinstance(binding, TaskInputBinding):
                params[name] = get_path(task_input, binding.path)
            elif isinstance(binding, ToolOutputBinding):
                params[name] = get_path(outputs[binding.source_node_id], binding.path)
            else:  # pragma: no cover - guarded by execution_blockers
                raise WorkflowExecutionError(f"unresolved parameter {node_id}.{name}")
        outputs[node_id] = registry.invoke(node.tool, params)

    result_node_ids = workflow.result_node_ids()
    if len(result_node_ids) == 1:
        final_output: JsonValue = outputs[result_node_ids[0]]
    else:
        final_output = {node_id: outputs[node_id] for node_id in result_node_ids}
    return ExecutionResult(
        workflow_id=workflow.workflow_id,
        outputs=outputs,
        final_output=final_output,
    )


@dataclass
class CustomerSupportSimulator:
    """In-memory-only tools; no network, messaging, or refund capability."""

    customers: dict[str, dict[str, JsonValue]]
    orders: dict[str, dict[str, JsonValue]]
    tickets: dict[str, dict[str, JsonValue]]

    @classmethod
    def for_state(cls, state_before: dict[str, JsonValue]) -> CustomerSupportSimulator:
        tickets = state_before.get("tickets")
        if not isinstance(tickets, dict):
            raise TypeError("simulation state_before must contain a tickets object")
        if not all(
            isinstance(ticket_id, str) and isinstance(ticket, dict)
            for ticket_id, ticket in tickets.items()
        ):
            raise TypeError("simulation tickets must map string IDs to objects")
        return cls(
            customers=copy.deepcopy(_SYNTHETIC_CUSTOMERS),
            orders=copy.deepcopy(_SYNTHETIC_ORDERS),
            tickets=copy.deepcopy(tickets),
        )

    def snapshot(self) -> dict[str, JsonValue]:
        return {"tickets": copy.deepcopy(self.tickets)}

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            {
                "lookup_customer": self.lookup_customer,
                "lookup_order": self.lookup_order,
                "classify_issue": self.classify_issue,
                "recommend_action": self.recommend_action,
                "update_ticket": self.update_ticket,
            }
        )

    def lookup_customer(self, customer_id: str) -> JsonValue:
        if customer_id not in self.customers:
            raise KeyError(f"unknown synthetic customer '{customer_id}'")
        return copy.deepcopy(self.customers[customer_id])

    def lookup_order(self, order_id: str, customer_id: str) -> JsonValue:
        if order_id not in self.orders:
            raise KeyError(f"unknown synthetic order '{order_id}'")
        order = self.orders[order_id]
        if order["customer_id"] != customer_id:
            raise ValueError("synthetic order does not belong to customer")
        return copy.deepcopy(order)

    def classify_issue(
        self,
        ticket_text: str,
        order_status: str,
        delivered: bool,
        damaged: bool,
        duplicate_charge: bool,
    ) -> JsonValue:
        del ticket_text
        if duplicate_charge:
            issue_type, eligible = "billing_duplicate", True
        elif damaged:
            issue_type, eligible = "damaged_item", True
        elif not delivered and order_status in {"processing", "shipped"}:
            issue_type, eligible = "delivery_delay", False
        else:
            issue_type, eligible = "general_review", False
        return {"issue_type": issue_type, "eligible": eligible}

    def recommend_action(
        self,
        issue_type: str,
        eligible: bool,
        policy_version: str,
    ) -> JsonValue:
        if policy_version != "v1":
            raise ValueError("unsupported synthetic policy version")
        recommendations = {
            "billing_duplicate": ("manual_refund_review", "pending_review"),
            "damaged_item": ("replacement_offer", "replacement_offered"),
            "delivery_delay": ("carrier_investigation", "pending_carrier"),
            "general_review": ("human_review", "pending_review"),
        }
        recommendation, status = recommendations[issue_type]
        return {
            "issue_type": issue_type,
            "eligible": eligible,
            "policy_version": policy_version,
            "recommendation": recommendation,
            "status": status,
        }

    def update_ticket(
        self,
        ticket_id: str,
        status: str,
        recommendation: str,
        issue_type: str,
    ) -> JsonValue:
        if ticket_id not in self.tickets:
            raise KeyError(f"unknown synthetic ticket '{ticket_id}'")
        self.tickets[ticket_id].update(
            {
                "status": status,
                "recommendation": recommendation,
                "issue_type": issue_type,
            }
        )
        return copy.deepcopy(self.tickets[ticket_id])


def replay_structure(workflow: WorkflowIR, run: TraceRun) -> ReplayStructureResult:
    """Check recorded shape only; never claim execution equivalence."""

    workflow_tools = {node.tool for node in workflow.nodes}
    run_steps = {step.id: step for step in run.steps}
    run_tools = {step.tool for step in run.steps}
    node_tools = {node.id: node.tool for node in workflow.nodes}
    observed_edges = {
        (run_steps[source].tool, target.tool)
        for target in run.steps
        for source in target.depends_on
    }
    expected_edges = {
        (node_tools[edge.source_node_id], node_tools[edge.target_node_id])
        for edge in workflow.edges
    }
    return ReplayStructureResult(
        tools_present=workflow_tools <= run_tools,
        dependencies_present=expected_edges <= observed_edges,
    )


def verify_workflow(
    workflow: WorkflowIR,
    compile_dataset: TraceDataset,
    test_dataset: TraceDataset,
) -> VerificationReport:
    """Execute every held-out run against fresh independent simulator state."""

    if compile_dataset.partition is not DatasetPartition.COMPILE:
        raise ValueError("compile dataset must use the 'compile' partition")
    if test_dataset.partition is not DatasetPartition.TEST:
        raise ValueError("test dataset must use the 'test' partition")
    assert_disjoint(compile_dataset, test_dataset)
    source_sha256 = hashlib.sha256(
        canonical_json(compile_dataset).encode("utf-8")
    ).hexdigest()
    if workflow.source_sha256 != source_sha256:
        raise ValueError("workflow was not built from the supplied compile dataset")

    cases: list[VerificationCaseResult] = []
    for run in test_dataset.runs:
        simulator = CustomerSupportSimulator.for_state(run.state_before)
        actual_before = simulator.snapshot()
        expected_changes = state_diff(run.state_before, run.state_after)
        try:
            if _token(actual_before) != _token(run.state_before):
                raise WorkflowExecutionError("simulator initial state does not match case")
            execution = execute_local(workflow, run.inputs, simulator.registry())
            actual_after = simulator.snapshot()
            actual_changes = state_diff(actual_before, actual_after)
            output_match = _token(execution.final_output) == _token(run.final_output)
            state_match = _token(actual_after) == _token(run.state_after)
            cases.append(
                VerificationCaseResult(
                    run_id=run.id,
                    status="passed" if output_match and state_match else "failed",
                    final_output_match=output_match,
                    state_match=state_match,
                    expected_final_output=run.final_output,
                    actual_final_output=execution.final_output,
                    expected_changes=expected_changes,
                    actual_changes=actual_changes,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report controlled case failure
            cases.append(
                VerificationCaseResult(
                    run_id=run.id,
                    status="error",
                    final_output_match=False,
                    state_match=False,
                    expected_final_output=run.final_output,
                    expected_changes=expected_changes,
                    actual_changes=state_diff(actual_before, simulator.snapshot()),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return VerificationReport(
        compile_dataset_id=compile_dataset.dataset_id,
        test_dataset_id=test_dataset.dataset_id,
        workflow_id=workflow.workflow_id,
        cases=cases,
        passed=bool(cases) and all(case.status == "passed" for case in cases),
    )


_SYNTHETIC_CUSTOMERS: dict[str, dict[str, JsonValue]] = {
    "C-001": {"customer_id": "C-001", "name": "Synthetic A", "tier": "standard"},
    "C-002": {"customer_id": "C-002", "name": "Synthetic B", "tier": "gold"},
    "C-003": {"customer_id": "C-003", "name": "Synthetic C", "tier": "standard"},
    "C-101": {"customer_id": "C-101", "name": "Synthetic Holdout A", "tier": "gold"},
    "C-102": {"customer_id": "C-102", "name": "Synthetic Holdout B", "tier": "standard"},
}

_SYNTHETIC_ORDERS: dict[str, dict[str, JsonValue]] = {
    "O-001": {"order_id": "O-001", "customer_id": "C-001", "status": "shipped", "delivered": False, "damaged": False, "duplicate_charge": False},
    "O-002": {"order_id": "O-002", "customer_id": "C-002", "status": "delivered", "delivered": True, "damaged": False, "duplicate_charge": True},
    "O-003": {"order_id": "O-003", "customer_id": "C-003", "status": "delivered", "delivered": True, "damaged": True, "duplicate_charge": False},
    "O-101": {"order_id": "O-101", "customer_id": "C-101", "status": "processing", "delivered": False, "damaged": False, "duplicate_charge": False},
    "O-102": {"order_id": "O-102", "customer_id": "C-102", "status": "delivered", "delivered": True, "damaged": True, "duplicate_charge": False},
}

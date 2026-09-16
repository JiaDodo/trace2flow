"""Frozen-shape M13b delivery registration used by the M13c comparison.

This is an explicitly AI-reviewed development contract, not an automatically
promoted production workflow. M13b tests independently exercise the full
recording -> upstream compiler -> Workflow IR path for the same five tools.
"""

from __future__ import annotations

import hashlib
import json

from .candidate import AlignmentStatus, DependencyEvidence, OccurrenceReference
from .ir import (
    BindingEvidence,
    ConstantBinding,
    ResolutionStatus,
    TaskInputBinding,
    WorkflowEdge,
    WorkflowIR,
    WorkflowNode,
)
from .models import SideEffect
from .support_router import (
    DeliveryRouteContract,
    PromotionReview,
    WorkflowRegistration,
    WorkflowVerification,
    workflow_sha256,
)

_RUNS = ("m13b-reference-a", "m13b-reference-b")


def _occurrences(tool: str) -> list[OccurrenceReference]:
    return [
        OccurrenceReference(
            run_id=run_id,
            step_id=f"{tool}-{run_id[-1]}",
            qualified_id=f"{run_id}:{tool}-{run_id[-1]}",
        )
        for run_id in _RUNS
    ]


def _constant(tool: str, value):
    return ConstantBinding(
        value=value,
        evidence=[
            BindingEvidence(
                run_id=run_id,
                target_occurrence_id=f"{run_id}:{tool}-{run_id[-1]}",
                source_kind="constant",
                observed_value=value,
            )
            for run_id in _RUNS
        ],
    )


def _runtime(tool: str, parameter: str, observed):
    return TaskInputBinding(
        path=[parameter],
        evidence_mode="declared_runtime_contract",
        evidence=[
            BindingEvidence(
                run_id=run_id,
                target_occurrence_id=f"{run_id}:{tool}-{run_id[-1]}",
                source_kind="task_input",
                source_path=[parameter],
                observed_value=observed,
                validation="declared_runtime_contract",
            )
            for run_id in _RUNS
        ],
    )


def _node(node_id: str, tool: str, parameters: dict, effects: list[SideEffect]):
    return WorkflowNode(
        id=node_id,
        tool=tool,
        occurrences=_occurrences(tool),
        parameters=parameters,
        side_effects=effects,
        alignment_status=AlignmentStatus.ALIGNED,
        branch_resolution=ResolutionStatus.RESOLVED,
        side_effect_resolution=ResolutionStatus.RESOLVED,
    )


def _edge(edge_id: str, source: str, target: str, source_tool: str, target_tool: str):
    return WorkflowEdge(
        id=edge_id,
        source_node_id=source,
        target_node_id=target,
        evidence=[
            DependencyEvidence(
                run_id=run_id,
                source_occurrence_id=f"{run_id}:{source_tool}-{run_id[-1]}",
                target_occurrence_id=f"{run_id}:{target_tool}-{run_id[-1]}",
            )
            for run_id in _RUNS
        ],
    )


def reference_delivery_workflow() -> WorkflowIR:
    source = {
        "schema_version": "m13b-reference-source/1.0",
        "runs": list(_RUNS),
        "reviewer_kind": "ai",
        "claim": "development contract matching the M13b compiled fixture",
    }
    source_hash = hashlib.sha256(
        json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    nodes = [
        _node(
            "context",
            "get_support_context",
            {},
            [SideEffect(kind="read", target="mock.support_context")],
        ),
        _node(
            "recent",
            "list_recent_orders",
            {"limit": _constant("list_recent_orders", 5)},
            [SideEffect(kind="read", target="mock.orders")],
        ),
        _node(
            "shipping",
            "get_shipping_status",
            {"order_id": _runtime("get_shipping_status", "order_id", "O-1001")},
            [SideEffect(kind="read", target="mock.shipping")],
        ),
        _node(
            "policy",
            "search_support_policy",
            {"topic": _constant("search_support_policy", "delivery_delay")},
            [SideEffect(kind="read", target="mock.policies")],
        ),
        _node(
            "update",
            "update_ticket",
            {
                "status": _constant("update_ticket", "pending_carrier"),
                "category": _constant("update_ticket", "delivery_delay"),
                "summary": _runtime(
                    "update_ticket",
                    "summary",
                    "reviewed runtime summary",
                ),
                "idempotency_key": _runtime(
                    "update_ticket",
                    "idempotency_key",
                    "T-100:delivery:O-1001",
                ),
            },
            [SideEffect(kind="write", target="mock.tickets", reversible=True)],
        ),
    ]
    return WorkflowIR(
        workflow_id="m13b-reviewed-delivery-v1",
        source_dataset_id="m13b-scripted-reviewed-development",
        source_sha256=source_hash,
        nodes=nodes,
        edges=[
            _edge("context-recent", "context", "recent", "get_support_context", "list_recent_orders"),
            _edge("recent-shipping", "recent", "shipping", "list_recent_orders", "get_shipping_status"),
            _edge("shipping-update", "shipping", "update", "get_shipping_status", "update_ticket"),
            _edge("policy-update", "policy", "update", "search_support_policy", "update_ticket"),
        ],
        unresolved_dependencies=0,
        output_node_ids=["update"],
    )


def reference_delivery_registration() -> WorkflowRegistration:
    workflow = reference_delivery_workflow()
    digest = workflow_sha256(workflow)
    return WorkflowRegistration(
        workflow_name="delivery_delay",
        version="1.0.0",
        workflow=workflow,
        workflow_sha256=digest,
        contract=DeliveryRouteContract(
            contract_id="delivery-delay-explicit-order-v1",
            delivery_terms=["物流", "快递", "包裹", "送到"],
            delay_terms=["没更新", "未更新", "没到", "未到", "延迟", "逾期"],
            conflicting_terms=["退款", "重复扣款", "破损", "坏了", "换货", "取消"],
        ),
        verification=WorkflowVerification(
            workflow_sha256=digest,
            verifier="m13b-offline-paired-development",
            cases_verified=2,
        ),
        promotion=PromotionReview(
            workflow_sha256=digest,
            reviewer="m13b-ai-engineering-review",
            reviewer_kind="ai",
            rationale="Narrow delivery workflow explicitly promoted for M13c comparison.",
        ),
    )

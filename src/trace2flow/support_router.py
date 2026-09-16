"""Conservative registry and router for Agent-plus-Trace2Flow execution.

Only explicitly promoted, hash-bound and structurally verified workflows can
run. Matching is intentionally narrow; uncertainty falls back to the standard
Agent. Workflow writes retain local evidence checks and human approval.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from .ir import ConstantBinding, TaskInputBinding, WorkflowIR, workflow_ir_json
from .models import StrictModel, json_compatible
from .runtime import ToolRegistry
from .simulation import ExecutionResult, execute_local
from .support_agent import AgentTurn, SupportRequest
from .support_backend import SupportBackend

SUPPORTED_WORKFLOW_TOOLS = frozenset(
    {
        "get_support_context",
        "list_recent_orders",
        "get_shipping_status",
        "search_support_policy",
        "update_ticket",
    }
)
_ORDER_ID = re.compile(r"(?<![A-Za-z0-9-])O-[0-9]+(?![A-Za-z0-9-])")


def workflow_sha256(workflow: WorkflowIR) -> str:
    return hashlib.sha256(workflow_ir_json(workflow).encode()).hexdigest()


class DeliveryRouteContract(StrictModel):
    schema_version: Literal["support-route-contract/1.0"] = (
        "support-route-contract/1.0"
    )
    contract_id: str = Field(min_length=1)
    intent: Literal["delivery_delay"] = "delivery_delay"
    requires_explicit_order_id: Literal[True] = True
    delivery_terms: list[str] = Field(min_length=1)
    delay_terms: list[str] = Field(min_length=1)
    conflicting_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terms(self) -> DeliveryRouteContract:
        for name in ("delivery_terms", "delay_terms", "conflicting_terms"):
            terms = getattr(self, name)
            if any(not term.strip() or term != term.strip() for term in terms):
                raise ValueError(f"{name} must contain non-empty trimmed terms")
            if len(terms) != len(set(terms)):
                raise ValueError(f"{name} must not contain duplicates")
        return self

    def match(self, message: str) -> tuple[str | None, str]:
        order_ids = sorted(set(_ORDER_ID.findall(message)))
        if len(order_ids) != 1:
            return None, "explicit_single_order_id_required"
        if any(term in message for term in self.conflicting_terms):
            return None, "conflicting_intent"
        if not any(term in message for term in self.delivery_terms):
            return None, "delivery_intent_not_explicit"
        if not any(term in message for term in self.delay_terms):
            return None, "delay_intent_not_explicit"
        return order_ids[0], "contract_match"


class WorkflowVerification(StrictModel):
    schema_version: Literal["support-workflow-verification/1.0"] = (
        "support-workflow-verification/1.0"
    )
    workflow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifier: str = Field(min_length=1)
    population_role: Literal["development"] = "development"
    cases_verified: int = Field(ge=1)
    output_checked: Literal[True] = True
    full_state_checked: Literal[True] = True
    result: Literal["passed"] = "passed"


class PromotionReview(StrictModel):
    schema_version: Literal["support-workflow-promotion/1.0"] = (
        "support-workflow-promotion/1.0"
    )
    workflow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    reviewer_kind: Literal["human", "ai", "automated_test"]
    approved: Literal[True] = True
    rationale: str = Field(min_length=10)


class WorkflowRegistration(StrictModel):
    schema_version: Literal["support-workflow-registration/1.0"] = (
        "support-workflow-registration/1.0"
    )
    workflow_name: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    workflow: WorkflowIR
    workflow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract: DeliveryRouteContract
    verification: WorkflowVerification
    promotion: PromotionReview

    @property
    def key(self) -> str:
        return f"{self.workflow_name}@{self.version}"


def _single_node_by_tool(workflow: WorkflowIR) -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    for node in workflow.nodes:
        if node.tool in nodes:
            raise ValueError(f"workflow repeats unsupported tool family '{node.tool}'")
        nodes[node.tool] = node
    return nodes


def validate_delivery_workflow(workflow: WorkflowIR) -> None:
    blockers = workflow.execution_blockers()
    if blockers:
        raise ValueError("workflow has execution blockers: " + "; ".join(blockers))
    tools = {node.tool for node in workflow.nodes}
    if tools != SUPPORTED_WORKFLOW_TOOLS:
        raise ValueError(
            "delivery workflow tool set must be exactly: "
            + ", ".join(sorted(SUPPORTED_WORKFLOW_TOOLS))
        )
    nodes = _single_node_by_tool(workflow)
    expected_parameters = {
        "get_support_context": set(),
        "list_recent_orders": {"limit"},
        "get_shipping_status": {"order_id"},
        "search_support_policy": {"topic"},
        "update_ticket": {"status", "category", "summary", "idempotency_key"},
    }
    for tool, expected in expected_parameters.items():
        if set(nodes[tool].parameters) != expected:
            raise ValueError(f"workflow parameters for '{tool}' do not match contract")

    recent_limit = nodes["list_recent_orders"].parameters["limit"]
    shipping_order = nodes["get_shipping_status"].parameters["order_id"]
    policy_topic = nodes["search_support_policy"].parameters["topic"]
    update = nodes["update_ticket"].parameters
    if not isinstance(recent_limit, ConstantBinding) or not (
        isinstance(recent_limit.value, int)
        and not isinstance(recent_limit.value, bool)
        and 1 <= recent_limit.value <= 10
    ):
        raise ValueError("recent-order limit must be an explicitly declared integer")
    if not isinstance(shipping_order, TaskInputBinding) or shipping_order.path != [
        "order_id"
    ] or shipping_order.evidence_mode != "declared_runtime_contract":
        raise ValueError("shipping order must bind to declared runtime order_id")
    if not isinstance(policy_topic, ConstantBinding) or policy_topic.value != (
        "delivery_delay"
    ):
        raise ValueError("policy topic must be the declared delivery_delay constant")
    constants = {"status": "pending_carrier", "category": "delivery_delay"}
    for parameter, value in constants.items():
        binding = update[parameter]
        if not isinstance(binding, ConstantBinding) or binding.value != value:
            raise ValueError(f"update {parameter} has an unsafe binding")
    for parameter in ("summary", "idempotency_key"):
        binding = update[parameter]
        if (
            not isinstance(binding, TaskInputBinding)
            or binding.path != [parameter]
            or binding.evidence_mode != "declared_runtime_contract"
        ):
            raise ValueError(f"update {parameter} must use its runtime input")

    edge_pairs = {(edge.source_node_id, edge.target_node_id) for edge in workflow.edges}
    required_edges = {
        (nodes["get_support_context"].id, nodes["list_recent_orders"].id),
        (nodes["list_recent_orders"].id, nodes["get_shipping_status"].id),
        (nodes["get_shipping_status"].id, nodes["update_ticket"].id),
        (nodes["search_support_policy"].id, nodes["update_ticket"].id),
    }
    if not required_edges.issubset(edge_pairs):
        raise ValueError("delivery workflow lacks required reviewed evidence edges")
    if workflow.result_node_ids() != [nodes["update_ticket"].id]:
        raise ValueError("delivery workflow output must be the ticket update")


class WorkflowRegistry:
    """Append-only in-process registry; registrations cannot replace each other."""

    def __init__(self) -> None:
        self._entries: dict[str, WorkflowRegistration] = {}

    def register(self, entry: WorkflowRegistration) -> None:
        digest = workflow_sha256(entry.workflow)
        if entry.workflow_sha256 != digest:
            raise ValueError("registration workflow hash mismatch")
        if entry.verification.workflow_sha256 != digest:
            raise ValueError("verification refers to another workflow")
        if entry.promotion.workflow_sha256 != digest:
            raise ValueError("promotion review refers to another workflow")
        validate_delivery_workflow(entry.workflow)
        if entry.key in self._entries:
            raise ValueError(f"workflow registration '{entry.key}' already exists")
        self._entries[entry.key] = entry.model_copy(deep=True)

    def get(self, key: str) -> WorkflowRegistration:
        try:
            return self._entries[key].model_copy(deep=True)
        except KeyError:
            raise KeyError(f"unknown workflow registration '{key}'") from None

    def resolve(
        self, request: SupportRequest
    ) -> tuple[WorkflowRegistration | None, str | None, str]:
        matches: list[tuple[WorkflowRegistration, str]] = []
        reasons: list[str] = []
        for key in sorted(self._entries):
            entry = self._entries[key]
            order_id, reason = entry.contract.match(request.message)
            reasons.append(f"{key}:{reason}")
            if order_id is not None:
                matches.append((entry, order_id))
        if not matches:
            return None, None, "no_registered_contract_match:" + ",".join(reasons)
        if len(matches) != 1:
            return None, None, "multiple_registered_contract_matches"
        entry, order_id = matches[0]
        return entry.model_copy(deep=True), order_id, "reviewed_contract_match"

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))


@dataclass
class _SupportWorkflowRuntime:
    backend: SupportBackend
    customer_id: str
    ticket_id: str
    calls: list[dict[str, JsonValue]] = field(default_factory=list)
    recent_order_ids: set[str] = field(default_factory=set)
    shipping: dict[str, JsonValue] | None = None
    policy: dict[str, JsonValue] | None = None
    context_seen: bool = False

    def _record(self, tool: str, params: dict, output: JsonValue) -> JsonValue:
        self.calls.append(
            {"tool": tool, "params": json_compatible(params), "output": output}
        )
        return output

    def get_support_context(self) -> JsonValue:
        output = self.backend.support_context(self.customer_id, self.ticket_id)
        self.context_seen = True
        return self._record("get_support_context", {}, output)

    def list_recent_orders(self, limit: int) -> JsonValue:
        output = self.backend.recent_orders(self.customer_id, limit)
        self.recent_order_ids = {item["order_id"] for item in output}
        return self._record("list_recent_orders", {"limit": limit}, output)

    def get_shipping_status(self, order_id: str) -> JsonValue:
        if order_id not in self.recent_order_ids:
            raise ValueError("workflow order requires reviewed recent-order evidence")
        output = self.backend.shipping_status(self.customer_id, order_id)
        self.shipping = output
        return self._record("get_shipping_status", {"order_id": order_id}, output)

    def search_support_policy(self, topic: str) -> JsonValue:
        output = self.backend.policy(topic)
        self.policy = output
        return self._record("search_support_policy", {"topic": topic}, output)

    def update_ticket(
        self,
        status: str,
        category: str,
        summary: str,
        idempotency_key: str,
    ) -> JsonValue:
        shipping, policy = self.shipping, self.policy
        if not self.context_seen:
            raise ValueError("workflow update requires trusted context evidence")
        if shipping is None or not (
            shipping.get("status") in {"in_transit", "exception"}
            and isinstance(shipping.get("estimated_delivery"), str)
            and shipping["estimated_delivery"] < self.backend.current_date
        ):
            raise ValueError("workflow update requires verified delayed shipping facts")
        if policy is None or not (
            policy.get("ticket_status") == status and category == "delivery_delay"
        ):
            raise ValueError("workflow update requires matching current policy evidence")
        output = self.backend.update_ticket(
            authenticated_customer_id=self.customer_id,
            ticket_id=self.ticket_id,
            status=status,
            category=category,
            summary=summary,
            idempotency_key=idempotency_key,
        )
        return self._record(
            "update_ticket",
            {
                "status": status,
                "category": category,
                "summary": summary,
                "idempotency_key": idempotency_key,
            },
            output,
        )

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            {
                "get_support_context": self.get_support_context,
                "list_recent_orders": self.list_recent_orders,
                "get_shipping_status": self.get_shipping_status,
                "search_support_policy": self.search_support_policy,
                "update_ticket": self.update_ticket,
            }
        )


def execute_support_workflow(
    workflow: WorkflowIR,
    task_input: dict[str, JsonValue],
    backend: SupportBackend,
    *,
    authenticated_customer_id: str,
    ticket_id: str,
) -> tuple[ExecutionResult, list[dict[str, JsonValue]]]:
    validate_delivery_workflow(workflow)
    runtime = _SupportWorkflowRuntime(
        backend=backend,
        customer_id=authenticated_customer_id,
        ticket_id=ticket_id,
    )
    result = execute_local(workflow, task_input, runtime.registry())
    return result, copy.deepcopy(runtime.calls)


class AdaptiveSupportTurn(StrictModel):
    schema_version: Literal["adaptive-support-turn/1.0"] = (
        "adaptive-support-turn/1.0"
    )
    status: Literal["completed", "approval_required", "error"]
    route: Literal["workflow", "agent"]
    route_reason: str
    thread_id: str
    answer: str | None = None
    pending_actions: list[dict[str, JsonValue]] = Field(default_factory=list)
    error_type: str | None = None
    trace: dict[str, JsonValue]


@dataclass
class _PendingWorkflow:
    request: SupportRequest
    registration_key: str
    workflow_sha256: str
    task_input: dict[str, JsonValue]
    trace: dict[str, JsonValue]


class AdaptiveSupportRouter:
    """Choose a reviewed workflow narrowly; otherwise preserve Agent behavior."""

    def __init__(
        self,
        *,
        agent: Any,
        backend: SupportBackend,
        registry: WorkflowRegistry,
    ) -> None:
        agent_backend = getattr(agent, "backend", backend)
        if agent_backend is not backend:
            raise ValueError("router and fallback Agent must share one backend")
        self.agent = agent
        self.backend = backend
        self.registry = registry
        self._pending: dict[str, _PendingWorkflow] = {}
        self._agent_pending: set[str] = set()
        self._thread_identities: dict[str, tuple[str, str]] = {}

    def _agent_turn(
        self, request: SupportRequest, reason: str, turn: AgentTurn
    ) -> AdaptiveSupportTurn:
        if turn.status == "approval_required":
            self._agent_pending.add(request.thread_id)
        return AdaptiveSupportTurn(
            status=turn.status,
            route="agent",
            route_reason=reason,
            thread_id=request.thread_id,
            answer=turn.answer,
            pending_actions=turn.pending_actions,
            error_type=turn.error_type,
            trace={
                "schema_version": "adaptive-route-trace/1.0",
                "route": "agent",
                "reason": reason,
                "request": request.model_dump(mode="json"),
                "agent_trace": turn.trace,
            },
        )

    def _fallback(self, request: SupportRequest, reason: str) -> AdaptiveSupportTurn:
        turn: AgentTurn = self.agent.invoke(request)
        return self._agent_turn(request, reason, turn)

    def invoke(self, request: SupportRequest) -> AdaptiveSupportTurn:
        if request.thread_id in self._pending or request.thread_id in self._agent_pending:
            raise ValueError("thread has a pending write decision")
        identity = (request.authenticated_customer_id, request.ticket_id)
        previous = self._thread_identities.setdefault(request.thread_id, identity)
        if previous != identity:
            raise ValueError("thread identity and ticket are immutable")
        entry, order_id, reason = self.registry.resolve(request)
        if entry is None or order_id is None:
            return self._fallback(request, reason)

        task_input: dict[str, JsonValue] = {
            "order_id": order_id,
            "summary": (
                f"已由审核工作流核实订单 {order_id} 的配送延迟事实，"
                "并按当前本地政策记录承运商调查。"
            ),
            "idempotency_key": f"{request.ticket_id}:delivery:{order_id}",
        }
        before = self.backend.snapshot()
        preview_backend = self.backend.clone()
        try:
            preview, preview_calls = execute_support_workflow(
                entry.workflow,
                task_input,
                preview_backend,
                authenticated_customer_id=request.authenticated_customer_id,
                ticket_id=request.ticket_id,
            )
        except (LookupError, ValueError, TypeError) as exc:
            if self.backend.snapshot() != before:
                raise RuntimeError("workflow preview changed the live backend") from None
            return self._fallback(
                request, f"workflow_preflight_failed:{type(exc).__name__}"
            )
        if self.backend.snapshot() != before:
            raise RuntimeError("workflow preview changed the live backend")
        pending_action = {
            "name": "execute_registered_workflow",
            "args": {
                "registration": entry.key,
                "workflow_id": entry.workflow.workflow_id,
                "order_id": order_id,
                "ticket_id": request.ticket_id,
            },
            "description": "Execute the reviewed local workflow and update one ticket",
        }
        trace = json_compatible(
            {
                "schema_version": "adaptive-route-trace/1.0",
                "route": "workflow",
                "reason": reason,
                "request": request.model_dump(mode="json"),
                "registration": entry.key,
                "workflow_id": entry.workflow.workflow_id,
                "workflow_sha256": entry.workflow_sha256,
                "contract_id": entry.contract.contract_id,
                "preview_calls": preview_calls,
                "preview_final_output": preview.final_output,
                "state_before": before,
                "state_after": self.backend.snapshot(),
                "model_calls": 0,
                "approved": None,
            }
        )
        self._pending[request.thread_id] = _PendingWorkflow(
            request=request,
            registration_key=entry.key,
            workflow_sha256=entry.workflow_sha256,
            task_input=task_input,
            trace=trace,
        )
        return AdaptiveSupportTurn(
            status="approval_required",
            route="workflow",
            route_reason=reason,
            thread_id=request.thread_id,
            pending_actions=[pending_action],
            trace=trace,
        )

    def resume(
        self, thread_id: str, decision: Literal["approve", "reject"]
    ) -> AdaptiveSupportTurn:
        if thread_id in self._agent_pending:
            self._agent_pending.remove(thread_id)
            turn: AgentTurn = self.agent.resume(thread_id, decision)
            request = SupportRequest.model_validate(turn.trace["request"])
            return self._agent_turn(
                request, f"fallback_agent_write_{decision}", turn
            )
        try:
            pending = self._pending.pop(thread_id)
        except KeyError:
            raise ValueError("thread has no pending workflow decision") from None
        trace = copy.deepcopy(pending.trace)
        trace["approved"] = decision == "approve"
        if decision == "reject":
            trace["state_after"] = self.backend.snapshot()
            return AdaptiveSupportTurn(
                status="completed",
                route="workflow",
                route_reason="workflow_write_rejected",
                thread_id=thread_id,
                answer="未批准本地工单更新，系统未执行工作流写入。",
                trace=trace,
            )
        try:
            entry = self.registry.get(pending.registration_key)
            if entry.workflow_sha256 != pending.workflow_sha256:
                raise ValueError("registered workflow changed after approval request")
            result, calls = execute_support_workflow(
                entry.workflow,
                pending.task_input,
                self.backend,
                authenticated_customer_id=(
                    pending.request.authenticated_customer_id
                ),
                ticket_id=pending.request.ticket_id,
            )
        except Exception as exc:  # noqa: BLE001 - do not disclose backend details
            trace["execution_error_type"] = type(exc).__name__
            trace["state_after"] = self.backend.snapshot()
            return AdaptiveSupportTurn(
                status="error",
                route="workflow",
                route_reason="approved_workflow_failed",
                thread_id=thread_id,
                error_type=type(exc).__name__,
                trace=trace,
            )
        trace["execution_calls"] = calls
        trace["final_output"] = result.final_output
        trace["state_after"] = self.backend.snapshot()
        return AdaptiveSupportTurn(
            status="completed",
            route="workflow",
            route_reason="approved_reviewed_workflow_completed",
            thread_id=thread_id,
            answer=(
                f"已根据审核工作流将模拟工单 {pending.request.ticket_id} 更新为 "
                "pending_carrier。本次仅完成本地工单记录；未联系外部承运商、"
                "未发起退款，也不会自动通知。"
            ),
            trace=trace,
        )

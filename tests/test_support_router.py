"""M13b trace adapter, explicit promotion registry and conservative routing."""

from __future__ import annotations

import copy
import unittest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from trace2flow.candidate import build_candidate_dag
from trace2flow.ir import (
    BindingOverride,
    ConstantBindingSpec,
    ResolutionPlan,
    TaskInputBindingSpec,
    build_workflow_ir,
)
from trace2flow.models import DatasetPartition, SideEffect, TraceDataset
from trace2flow.support_agent import CustomerSupportAgent, SupportRequest
from trace2flow.support_backend import SupportBackend
from trace2flow.support_router import (
    AdaptiveSupportRouter,
    DeliveryRouteContract,
    PromotionReview,
    WorkflowRegistration,
    WorkflowRegistry,
    WorkflowVerification,
    workflow_sha256,
)
from trace2flow.support_trace import (
    SupportRecordingReview,
    merge_support_datasets,
    normalize_support_session,
    normalize_support_turn,
    support_recording_sha256,
)
from trace2flow.upstream import compile_with_upstream


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    cursor: int = 0
    bound_tool_schemas: dict[str, dict] = Field(default_factory=dict)

    @property
    def _llm_type(self):
        return "scripted-m13b-support-agent"

    def bind_tools(self, tools, **kwargs):
        del kwargs
        self.bound_tool_schemas = {tool.name: tool.args for tool in tools}
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del messages, stop, run_manager, kwargs
        message = self.responses[self.cursor]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def call(identifier: str, name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": identifier, "type": "tool_call"}
        ],
    )


def delivery_model(suffix: str) -> ScriptedModel:
    summary = (
        "已由审核工作流核实订单 O-1001 的配送延迟事实，"
        "并按当前本地政策记录承运商调查。"
    )
    return ScriptedModel(
        responses=[
            call(f"context-{suffix}", "get_support_context", {}),
            call(f"recent-{suffix}", "list_recent_orders", {"limit": 5}),
            call(
                f"shipping-{suffix}",
                "get_shipping_status",
                {"order_id": "O-1001"},
            ),
            call(
                f"policy-{suffix}",
                "search_support_policy",
                {"topic": "delivery_delay"},
            ),
            call(
                f"update-{suffix}",
                "update_ticket",
                {
                    "status": "pending_carrier",
                    "category": "delivery_delay",
                    "summary": summary,
                    "idempotency_key": "T-100:delivery:O-1001",
                },
            ),
            AIMessage(content="模型声称以后会继续通知用户。"),
        ]
    )


def support_request(thread: str, message: str) -> SupportRequest:
    return SupportRequest(
        thread_id=thread,
        ticket_id="T-100",
        authenticated_customer_id="C-100",
        message=message,
    )


def delivery_session_turns(suffix: str) -> list[dict]:
    backend = SupportBackend.demo()
    app = CustomerSupportAgent(delivery_model(suffix), backend, model_id="scripted")
    pending = app.invoke(
        support_request(
            f"compile-{suffix}",
            "订单 O-1001 的蓝牙耳机物流一直没更新，还没有送到。",
        )
    )
    if pending.status != "approval_required":
        raise AssertionError("scripted compile turn did not pause")
    completed = app.resume(f"compile-{suffix}", "approve")
    return [pending.model_dump(mode="json"), completed.model_dump(mode="json")]


def completed_delivery_turn(suffix: str) -> dict:
    return delivery_session_turns(suffix)[-1]


def review_for(turn: dict, reviewer: str) -> SupportRecordingReview:
    trace = turn["trace"]
    ids = {item["tool"]: item["id"] for item in trace["calls"]}
    dependencies = {
        ids["get_support_context"]: [],
        ids["list_recent_orders"]: [ids["get_support_context"]],
        ids["get_shipping_status"]: [ids["list_recent_orders"]],
        ids["search_support_policy"]: [],
        ids["update_ticket"]: [
            ids["get_shipping_status"],
            ids["search_support_policy"],
        ],
    }
    side_effects = {
        ids["get_support_context"]: [
            SideEffect(kind="read", target="mock.support_context")
        ],
        ids["list_recent_orders"]: [
            SideEffect(kind="read", target="mock.orders")
        ],
        ids["get_shipping_status"]: [
            SideEffect(kind="read", target="mock.shipping")
        ],
        ids["search_support_policy"]: [
            SideEffect(kind="read", target="mock.policies")
        ],
        ids["update_ticket"]: [
            SideEffect(kind="write", target="mock.tickets", reversible=True)
        ],
    }
    recording = normalize_recording_model(turn)
    return SupportRecordingReview(
        recording_sha256=support_recording_sha256(recording),
        reviewer=reviewer,
        reviewer_kind="automated_test",
        dependencies=dependencies,
        side_effects=side_effects,
        alignment_keys={call_id: None for call_id in dependencies},
    )


def normalize_recording_model(turn: dict):
    from trace2flow.support_trace import SupportTurnRecording

    return SupportTurnRecording.model_validate(turn).trace


def build_reviewed_workflow() -> tuple[TraceDataset, object]:
    normalized = []
    for suffix in ("a", "b"):
        turn = completed_delivery_turn(suffix)
        normalized.append(
            normalize_support_turn(
                turn,
                dataset_id=f"m13b-{suffix}",
                source=f"scripted-m13b-{suffix}",
                review=review_for(turn, f"automated-review-{suffix}"),
            )
        )
    dataset = merge_support_datasets(normalized, dataset_id="m13b-delivery-compile")
    upstream = compile_with_upstream(dataset).signals
    candidate = build_candidate_dag(dataset, upstream)
    nodes = {node.tool: node.id for node in candidate.nodes}
    overrides = [
        BindingOverride(
            node_id=nodes["list_recent_orders"],
            parameter="limit",
            binding=ConstantBindingSpec(value=5),
        ),
        BindingOverride(
            node_id=nodes["get_shipping_status"],
            parameter="order_id",
            binding=TaskInputBindingSpec(
                path=["order_id"], evidence_mode="declared_runtime_contract"
            ),
        ),
        BindingOverride(
            node_id=nodes["search_support_policy"],
            parameter="topic",
            binding=ConstantBindingSpec(value="delivery_delay"),
        ),
        BindingOverride(
            node_id=nodes["update_ticket"],
            parameter="status",
            binding=ConstantBindingSpec(value="pending_carrier"),
        ),
        BindingOverride(
            node_id=nodes["update_ticket"],
            parameter="category",
            binding=ConstantBindingSpec(value="delivery_delay"),
        ),
        BindingOverride(
            node_id=nodes["update_ticket"],
            parameter="summary",
            binding=TaskInputBindingSpec(
                path=["summary"], evidence_mode="declared_runtime_contract"
            ),
        ),
        BindingOverride(
            node_id=nodes["update_ticket"],
            parameter="idempotency_key",
            binding=TaskInputBindingSpec(
                path=["idempotency_key"], evidence_mode="declared_runtime_contract"
            ),
        ),
    ]
    plan = ResolutionPlan(
        binding_overrides=overrides,
        confirmed_branch_nodes=sorted(nodes.values()),
        confirmed_side_effect_nodes=sorted(nodes.values()),
        output_node_ids=[nodes["update_ticket"]],
    )
    workflow = build_workflow_ir(dataset, candidate, plan)
    if workflow.execution_blockers():
        raise AssertionError(workflow.execution_blockers())
    return dataset, workflow


def registration(workflow, *, name: str = "delivery_delay") -> WorkflowRegistration:
    digest = workflow_sha256(workflow)
    return WorkflowRegistration(
        workflow_name=name,
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
            rationale="Explicit narrow development-only delivery workflow promotion.",
        ),
    )


class TraceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.turn = completed_delivery_turn("adapter")

    def test_unreviewed_turn_is_lossless_quarantine_without_inferred_semantics(self):
        dataset = normalize_support_turn(
            self.turn,
            dataset_id="quarantine",
            source="scripted-adapter",
            partition=DatasetPartition.COMPILE,
        )
        self.assertEqual(dataset.metadata["import_review_status"], "required")
        self.assertEqual(
            dataset.runs[0].inputs["message"],
            "订单 O-1001 的蓝牙耳机物流一直没更新，还没有送到。",
        )
        self.assertNotIn("scenario", dataset.runs[0].inputs)
        self.assertNotIn("oracle", dataset.runs[0].inputs)
        self.assertTrue(all(not step.depends_on for step in dataset.runs[0].steps))
        self.assertTrue(all(not step.side_effects for step in dataset.runs[0].steps))
        with self.assertRaisesRegex(ValueError, "require complete"):
            build_candidate_dag(dataset, compile_with_upstream(dataset).signals)

    def test_repeated_calls_remain_distinct_and_json_types_survive(self):
        turn = copy.deepcopy(self.turn)
        repeated = copy.deepcopy(turn["trace"]["calls"][1])
        repeated["id"] = "second-recent-call"
        repeated["params"]["limit"] = 2
        repeated["output"] = [True, None, 2, "2"]
        turn["trace"]["calls"].append(repeated)
        dataset = normalize_support_turn(
            turn, dataset_id="repeated", source="scripted-repeated"
        )
        steps = dataset.runs[0].steps
        self.assertEqual(len(steps), 6)
        self.assertEqual(steps[-1].id, "second-recent-call")
        self.assertEqual(steps[-1].output, [True, None, 2, "2"])

    def test_review_is_hash_bound_exhaustive_and_state_change_needs_write(self):
        review = review_for(self.turn, "reviewer")
        bad_hash = review.model_copy(update={"recording_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "different recording"):
            normalize_support_turn(
                self.turn,
                dataset_id="bad-hash",
                source="scripted",
                review=bad_hash,
            )
        missing = review.model_copy(deep=True)
        missing.dependencies.pop(next(iter(missing.dependencies)))
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            normalize_support_turn(
                self.turn,
                dataset_id="missing",
                source="scripted",
                review=missing,
            )
        update_id = next(
            call["id"]
            for call in self.turn["trace"]["calls"]
            if call["tool"] == "update_ticket"
        )
        no_write = review.model_copy(deep=True)
        no_write.side_effects[update_id] = [SideEffect(kind="none")]
        with self.assertRaisesRegex(ValueError, "must declare a reviewed write"):
            normalize_support_turn(
                self.turn,
                dataset_id="no-write",
                source="scripted",
                review=no_write,
            )
        future = review.model_copy(deep=True)
        call_ids = [call["id"] for call in self.turn["trace"]["calls"]]
        future.dependencies[call_ids[0]] = [call_ids[-1]]
        with self.assertRaisesRegex(ValueError, "had not executed"):
            normalize_support_turn(
                self.turn,
                dataset_id="future-dependency",
                source="scripted",
                review=future,
            )

    def test_prompt_hash_tampering_is_rejected(self):
        turn = copy.deepcopy(self.turn)
        turn["trace"]["system_prompt"] += "tampered"
        with self.assertRaises(ValidationError):
            normalize_support_turn(turn, dataset_id="tampered", source="scripted")

    def test_saved_session_adapts_and_failed_runs_cannot_enter_promotion_merge(self):
        turns = delivery_session_turns("saved-session")
        session = {"schema_version": "support-agent-session/1.0", "turns": turns}
        dataset = normalize_support_session(
            session, dataset_id="saved-session", source="saved-cli-session"
        )
        self.assertEqual(len(dataset.runs), 1)
        self.assertEqual(dataset.runs[0].status.value, "completed")
        self.assertEqual(len(dataset.runs[0].steps), 5)
        self.assertEqual(dataset.metadata["import_review_status"], "required")

        turn = copy.deepcopy(self.turn)
        turn["trace"]["calls"][0]["status"] = "failed"
        turn["trace"]["calls"][0]["output"] = {"error": "redacted"}
        reviewed = normalize_support_turn(
            turn,
            dataset_id="reviewed-failure",
            source="scripted-failure",
            review=review_for(turn, "failure-reviewer"),
        )
        with self.assertRaisesRegex(ValueError, "fully successful"):
            merge_support_datasets([reviewed], dataset_id="not-promotable")


class AdaptiveRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset, cls.workflow = build_reviewed_workflow()

    def make_router(self, fallback_responses=None):
        backend = SupportBackend.demo()
        model = ScriptedModel(
            responses=fallback_responses
            or [AIMessage(content="请补充一个明确且属于您的订单号。")]
        )
        agent = CustomerSupportAgent(model, backend, model_id="scripted-fallback")
        registry = WorkflowRegistry()
        registry.register(registration(self.workflow))
        return AdaptiveSupportRouter(
            agent=agent, backend=backend, registry=registry
        ), backend, model, registry

    def test_reviewed_workflow_routes_with_approval_and_matches_agent_state(self):
        request = support_request(
            "paired-workflow",
            "订单 O-1001 的蓝牙耳机物流没更新，而且现在还没到。",
        )
        router, workflow_backend, fallback_model, _ = self.make_router()
        before = workflow_backend.snapshot()
        pending = router.invoke(request)
        self.assertEqual(pending.route, "workflow")
        self.assertEqual(pending.status, "approval_required")
        self.assertEqual(workflow_backend.snapshot(), before)
        self.assertEqual(pending.trace["model_calls"], 0)
        self.assertEqual(fallback_model.cursor, 0)
        self.assertEqual(set(pending.trace["request"]), set(SupportRequest.model_fields))

        completed = router.resume(request.thread_id, "approve")
        self.assertEqual(completed.status, "completed")
        self.assertIn("未联系外部承运商", completed.answer)
        self.assertEqual(workflow_backend.tickets["T-100"].revision, 1)
        tools = [call["tool"] for call in completed.trace["execution_calls"]]
        self.assertEqual(set(tools), {
            "get_support_context",
            "list_recent_orders",
            "get_shipping_status",
            "search_support_policy",
            "update_ticket",
        })
        self.assertLess(tools.index("get_support_context"), tools.index("list_recent_orders"))
        self.assertLess(tools.index("list_recent_orders"), tools.index("get_shipping_status"))
        self.assertLess(tools.index("get_shipping_status"), tools.index("update_ticket"))
        self.assertLess(tools.index("search_support_policy"), tools.index("update_ticket"))

        baseline_backend = SupportBackend.demo()
        baseline = CustomerSupportAgent(
            delivery_model("paired-agent"), baseline_backend, model_id="scripted"
        )
        agent_pending = baseline.invoke(
            request.model_copy(update={"thread_id": "paired-agent"})
        )
        self.assertEqual(agent_pending.status, "approval_required")
        agent_completed = baseline.resume("paired-agent", "approve")
        self.assertEqual(agent_completed.status, "completed")
        self.assertEqual(workflow_backend.snapshot(), baseline_backend.snapshot())

    def test_rejection_and_stale_fact_revalidation_never_write(self):
        router, backend, _, _ = self.make_router()
        request = support_request(
            "reject", "订单 O-1001 的包裹物流没更新，到现在还没到。"
        )
        before = backend.snapshot()
        router.invoke(request)
        rejected = router.resume("reject", "reject")
        self.assertEqual(rejected.status, "completed")
        self.assertEqual(backend.snapshot(), before)

        router, backend, _, _ = self.make_router()
        stale = support_request(
            "stale", "订单 O-1001 的包裹物流没更新，到现在还没到。"
        )
        router.invoke(stale)
        backend.shipping["O-1001"].estimated_delivery = "2026-09-20"
        failed = router.resume("stale", "approve")
        self.assertEqual(failed.status, "error")
        self.assertEqual(backend.tickets["T-100"].revision, 0)

    def test_ambiguity_conflict_and_preflight_failure_fall_back_to_agent(self):
        cases = [
            (
                "ambiguous",
                "我的蓝牙耳机物流没更新，还没有到。",
                "no_registered_contract_match",
            ),
            (
                "conflict",
                "订单 O-1001 物流没更新，我还要退款。",
                "no_registered_contract_match",
            ),
            (
                "unknown",
                "订单 O-9999 的包裹物流没更新，还没有到。",
                "workflow_preflight_failed:",
            ),
        ]
        for thread, message, reason in cases:
            with self.subTest(thread=thread):
                router, backend, model, _ = self.make_router()
                before = backend.snapshot()
                turn = router.invoke(support_request(thread, message))
                self.assertEqual(turn.route, "agent")
                self.assertIn(reason, turn.route_reason)
                self.assertEqual(model.cursor, 1)
                self.assertEqual(backend.snapshot(), before)

    def test_fallback_agent_approval_resumes_through_router(self):
        backend = SupportBackend.demo()
        model = delivery_model("fallback-resume")
        registry = WorkflowRegistry()
        registry.register(registration(self.workflow))
        router = AdaptiveSupportRouter(
            agent=CustomerSupportAgent(model, backend, model_id="scripted"),
            backend=backend,
            registry=registry,
        )
        # No explicit order ID means the workflow contract cannot match. The
        # scripted Agent independently resolves the local order and requests a write.
        pending = router.invoke(
            support_request("fallback-resume", "我的耳机物流一直没更新，还没到。")
        )
        self.assertEqual(pending.route, "agent")
        self.assertEqual(pending.status, "approval_required")
        self.assertEqual(backend.tickets["T-100"].revision, 0)
        completed = router.resume("fallback-resume", "approve")
        self.assertEqual(completed.route, "agent")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(backend.tickets["T-100"].revision, 1)

    def test_registry_is_hash_bound_append_only_and_ambiguous_matches_fallback(self):
        good = registration(self.workflow)
        bad = good.model_copy(update={"workflow_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            WorkflowRegistry().register(bad)
        unsafe_workflow = self.workflow.model_copy(deep=True)
        shipping = next(
            node for node in unsafe_workflow.nodes if node.tool == "get_shipping_status"
        )
        shipping.parameters["order_id"].evidence_mode = "observed_value_match"
        unsafe = registration(unsafe_workflow, name="unsafe_binding")
        with self.assertRaisesRegex(ValueError, "declared runtime order_id"):
            WorkflowRegistry().register(unsafe)
        registry = WorkflowRegistry()
        registry.register(good)
        with self.assertRaisesRegex(ValueError, "already exists"):
            registry.register(good)
        registry.register(registration(self.workflow, name="delivery_delay_shadow"))

        backend = SupportBackend.demo()
        model = ScriptedModel(responses=[AIMessage(content="由 Agent 继续处理。")])
        router = AdaptiveSupportRouter(
            agent=CustomerSupportAgent(model, backend, model_id="scripted"),
            backend=backend,
            registry=registry,
        )
        turn = router.invoke(
            support_request(
                "ambiguous-registry", "订单 O-1001 的物流没更新，而且还没到。"
            )
        )
        self.assertEqual(turn.route, "agent")
        self.assertEqual(turn.route_reason, "multiple_registered_contract_matches")

    def test_router_thread_identity_is_immutable_across_routes(self):
        router, _, _, _ = self.make_router()
        first = support_request(
            "fixed-identity", "订单 O-1001 的物流没更新，而且还没到。"
        )
        router.invoke(first)
        router.resume("fixed-identity", "reject")
        changed = first.model_copy(
            update={"authenticated_customer_id": "C-200", "ticket_id": "T-200"}
        )
        with self.assertRaisesRegex(ValueError, "immutable"):
            router.invoke(changed)

    def test_workflow_is_bound_to_reviewed_adapter_dataset(self):
        self.assertEqual(self.dataset.metadata["import_review_status"], "complete")
        self.assertEqual(len(self.dataset.runs), 2)
        self.assertEqual(self.workflow.source_dataset_id, self.dataset.dataset_id)
        self.assertFalse(self.workflow.execution_blockers())
        self.assertTrue(
            all(run.metadata["reviewer_kind"] == "automated_test" for run in self.dataset.runs)
        )


if __name__ == "__main__":
    unittest.main()

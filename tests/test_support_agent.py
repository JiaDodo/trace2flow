"""Standard support Agent baseline: natural turns, tools, HITL and trace safety."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from trace2flow.support_agent import (
    SUPPORT_AGENT_PROMPT,
    CustomerSupportAgent,
    SupportRequest,
    main,
)
from trace2flow.support_backend import SupportBackend


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    cursor: int = 0
    seen_messages: list[list[object]] = Field(default_factory=list)
    bound_tool_schemas: dict[str, dict] = Field(default_factory=dict)

    @property
    def _llm_type(self):
        return "scripted-standard-support-agent"

    def bind_tools(self, tools, **kwargs):
        del kwargs
        self.bound_tool_schemas = {tool.name: tool.args for tool in tools}
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del stop, run_manager, kwargs
        self.seen_messages.append(list(messages))
        message = self.responses[self.cursor]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


class FailingModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "failing-standard-support-agent"

    def bind_tools(self, tools, **kwargs):
        del tools, kwargs
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del messages, stop, run_manager, kwargs
        raise RuntimeError("provider secret detail")


def call(identifier: str, name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": identifier, "type": "tool_call"}
        ],
    )


def request(message: str, *, thread: str = "thread-1") -> SupportRequest:
    return SupportRequest(
        thread_id=thread,
        ticket_id="T-100",
        authenticated_customer_id="C-100",
        message=message,
    )


def successful_delivery_model() -> ScriptedModel:
    return ScriptedModel(
        responses=[
            call("call-1", "list_recent_orders", {"limit": 5}),
            call("call-2", "get_shipping_status", {"order_id": "O-1001"}),
            call("call-3", "search_support_policy", {"topic": "delivery_delay"}),
            call(
                "call-4",
                "update_ticket",
                {
                    "status": "pending_carrier",
                    "category": "delivery_delay",
                    "summary": "已核实耳机订单仍在运输且超过预计日期，记录物流调查。",
                    "idempotency_key": "T-100:delivery:O-1001",
                },
            ),
            AIMessage(content="已记录物流调查；目前没有退款，也没有向外部系统发消息。"),
        ]
    )


class BackendTests(unittest.TestCase):
    def test_demo_is_fresh_synthetic_and_request_has_no_hidden_answer_fields(self):
        one, two = SupportBackend.demo(), SupportBackend.demo()
        one.tickets["T-100"].summary = "changed"
        self.assertIsNone(two.tickets["T-100"].summary)
        fields = set(SupportRequest.model_fields)
        self.assertEqual(
            fields,
            {
                "thread_id",
                "ticket_id",
                "authenticated_customer_id",
                "message",
                "channel",
                "locale",
            },
        )
        self.assertTrue(
            {
                "scenario",
                "oracle",
                "expected_action",
                "order_id",
                "policy_version",
            }.isdisjoint(fields)
        )
        self.assertNotIn("real", json.dumps(two.snapshot()))

    def test_cross_customer_reads_are_indistinguishable_and_do_not_mutate(self):
        backend = SupportBackend.demo()
        before = backend.snapshot()
        with self.assertRaisesRegex(LookupError, "unavailable") as foreign:
            backend.order("C-100", "O-3001")
        with self.assertRaisesRegex(LookupError, "unavailable") as absent:
            backend.order("C-100", "DOES-NOT-EXIST")
        self.assertEqual(str(foreign.exception), str(absent.exception))
        self.assertEqual(backend.snapshot(), before)

    def test_ticket_write_is_owned_validated_and_idempotent(self):
        backend = SupportBackend.demo()
        args = {
            "authenticated_customer_id": "C-100",
            "ticket_id": "T-100",
            "status": "pending_carrier",
            "category": "delivery_delay",
            "summary": "已核实物流仍在运输，记录承运商调查。",
            "idempotency_key": "ticket:T-100:delivery:O-1001",
        }
        first = backend.update_ticket(**args)
        second = backend.update_ticket(**args)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(backend.tickets["T-100"].revision, 1)
        with self.assertRaises(ValueError):
            backend.update_ticket(
                **(args | {"summary": "另一个完全不同且足够长的写入摘要。"})
            )
        with self.assertRaises(LookupError):
            backend.update_ticket(**(args | {"authenticated_customer_id": "C-200"}))


class StandardAgentTests(unittest.TestCase):
    def test_tools_are_typed_and_runtime_identity_is_not_model_controlled(self):
        self.assertIn("不要承诺自动通知", SUPPORT_AGENT_PROMPT)
        model = ScriptedModel(responses=[AIMessage(content="请告诉我是哪一笔订单。")])
        app = CustomerSupportAgent(model, SupportBackend.demo(), model_id="scripted")
        app.invoke(request("我想咨询一下订单"))
        self.assertEqual(
            set(model.bound_tool_schemas),
            {
                "get_support_context",
                "list_recent_orders",
                "get_order",
                "get_shipping_status",
                "get_payment_events",
                "search_support_policy",
                "update_ticket",
            },
        )
        for schema in model.bound_tool_schemas.values():
            self.assertNotIn("authenticated_customer_id", schema)
            self.assertNotIn("ticket_id", schema)
            self.assertNotIn("runtime", schema)
        self.assertEqual(model.bound_tool_schemas["get_support_context"], {})
        self.assertEqual(
            model.bound_tool_schemas["list_recent_orders"]["limit"]["maximum"], 10
        )
        self.assertIn("enum", model.bound_tool_schemas["update_ticket"]["status"])

    def test_ambiguous_natural_request_asks_followup_without_write(self):
        model = ScriptedModel(
            responses=[
                call("call-1", "list_recent_orders", {"limit": 5}),
                AIMessage(content="您最近有耳机和数据线两笔订单，请问是哪一件商品？"),
            ]
        )
        backend = SupportBackend.demo()
        before = backend.snapshot()
        turn = CustomerSupportAgent(model, backend, model_id="scripted").invoke(
            request("我前几天买的东西怎么还没到啊")
        )
        self.assertEqual(turn.status, "completed")
        self.assertIn("哪一件", turn.answer)
        self.assertEqual(backend.snapshot(), before)
        self.assertEqual(
            [item["tool"] for item in turn.trace["calls"]], ["list_recent_orders"]
        )
        self.assertEqual(
            turn.trace["prompt_sha256"],
            hashlib.sha256(SUPPORT_AGENT_PROMPT.encode()).hexdigest(),
        )
        self.assertRegex(turn.trace["producer_sha256"], r"^[0-9a-f]{64}$")

    def test_conversation_memory_keeps_followup_in_same_thread(self):
        model = ScriptedModel(
            responses=[
                call("call-1", "list_recent_orders", {"limit": 5}),
                AIMessage(content="请问是耳机还是数据线？"),
                call("call-2", "get_shipping_status", {"order_id": "O-1001"}),
                call("call-3", "search_support_policy", {"topic": "delivery_delay"}),
                AIMessage(
                    content="耳机仍在运输，已经超过预计日期；是否需要我记录物流调查？"
                ),
            ]
        )
        app = CustomerSupportAgent(model, SupportBackend.demo(), model_id="scripted")
        first = app.invoke(request("我买的东西没到", thread="memory"))
        second = app.invoke(request("是上周买的耳机", thread="memory"))
        self.assertEqual(first.status, second.status, "completed")
        visible = [getattr(item, "content", "") for item in model.seen_messages[2]]
        self.assertIn("我买的东西没到", visible)
        self.assertIn("请问是耳机还是数据线？", visible)
        self.assertIn("是上周买的耳机", visible)
        self.assertEqual(
            [item["tool"] for item in second.trace["calls"]],
            ["get_shipping_status", "search_support_policy"],
        )

    def test_write_pauses_before_side_effect_then_approval_executes_once(self):
        backend = SupportBackend.demo()
        app = CustomerSupportAgent(
            successful_delivery_model(), backend, model_id="scripted"
        )
        turn = app.invoke(request("我那副耳机怎么还没到啊，上周就发货了"))
        self.assertEqual(turn.status, "approval_required")
        self.assertEqual(turn.pending_actions[0]["name"], "update_ticket")
        self.assertEqual(backend.tickets["T-100"].status, "open")
        self.assertEqual(
            [item["tool"] for item in turn.trace["calls"]],
            ["list_recent_orders", "get_shipping_status", "search_support_policy"],
        )
        completed = app.resume("thread-1", "approve")
        self.assertEqual(completed.status, "completed")
        self.assertIn("只完成了本地工单记录", completed.answer)
        self.assertIn("未联系任何外部承运商", completed.answer)
        self.assertNotIn("会跟进", completed.answer)
        self.assertEqual(completed.trace["events"][-1]["role"], "response_guard")
        self.assertEqual(backend.tickets["T-100"].status, "pending_carrier")
        self.assertEqual(backend.tickets["T-100"].revision, 1)
        write = completed.trace["calls"][-1]
        self.assertEqual(write["tool"], "update_ticket")
        self.assertTrue(write["state_changed"])
        self.assertTrue(
            any(
                item["role"] == "approval_decision" and item["decision"] == "approve"
                for item in completed.trace["events"]
            )
        )

    def test_rejected_write_returns_to_model_without_mutation(self):
        model = successful_delivery_model()
        model.responses[-1] = AIMessage(
            content="没有更新工单；已按您的决定取消本次写入。"
        )
        backend = SupportBackend.demo()
        app = CustomerSupportAgent(model, backend, model_id="scripted")
        pending = app.invoke(request("耳机一直没到"))
        before = backend.snapshot()
        rejected = app.resume("thread-1", "reject", feedback="先不要修改")
        self.assertEqual(pending.status, "approval_required")
        self.assertEqual(rejected.status, "completed")
        self.assertIn("没有更新", rejected.answer)
        self.assertEqual(backend.snapshot(), before)
        self.assertNotIn(
            "update_ticket", [item["tool"] for item in rejected.trace["calls"]]
        )

    def test_approved_write_still_fails_without_fact_and_policy_evidence(self):
        model = ScriptedModel(
            responses=[
                call(
                    "unsafe",
                    "update_ticket",
                    {
                        "status": "pending_carrier",
                        "category": "delivery_delay",
                        "summary": "没有查询事实，试图直接写入工单的测试摘要。",
                        "idempotency_key": "T-100:unsafe-direct",
                    },
                ),
                AIMessage(content="写入失败，因为缺少必要事实和政策依据。"),
            ]
        )
        backend = SupportBackend.demo()
        app = CustomerSupportAgent(model, backend, model_id="scripted")
        self.assertEqual(
            app.invoke(request("直接给我改掉")).status, "approval_required"
        )
        result = app.resume("thread-1", "approve")
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend.tickets["T-100"].status, "open")
        call_record = result.trace["calls"][-1]
        self.assertEqual(call_record["status"], "failed")
        self.assertEqual(call_record["error_type"], "ValueError")
        self.assertFalse(call_record["state_changed"])

    def test_delivery_write_requires_estimate_before_backend_current_date(self):
        backend = SupportBackend.demo()
        backend.current_date = "2026-09-12"
        app = CustomerSupportAgent(
            successful_delivery_model(), backend, model_id="scripted"
        )
        self.assertEqual(
            app.invoke(request("耳机还没到，但预计日期其实还没过")).status,
            "approval_required",
        )
        result = app.resume("thread-1", "approve")
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend.tickets["T-100"].status, "open")
        self.assertEqual(result.trace["calls"][-1]["status"], "failed")

    def test_foreign_and_unknown_order_errors_do_not_disclose_or_mutate(self):
        model = ScriptedModel(
            responses=[
                call("foreign", "get_order", {"order_id": "O-3001"}),
                call("missing", "get_order", {"order_id": "NOT-THERE"}),
                AIMessage(content="这两个订单号都无法用于当前已认证客户。"),
            ]
        )
        backend = SupportBackend.demo()
        before = backend.snapshot()
        result = CustomerSupportAgent(model, backend, model_id="scripted").invoke(
            request("帮我看看 O-3001 和 NOT-THERE")
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend.snapshot(), before)
        calls = result.trace["calls"]
        self.assertEqual([item["status"] for item in calls], ["failed", "failed"])
        self.assertEqual(
            [item["output"] for item in calls],
            [
                {"error": "tool call rejected or failed", "error_type": "LookupError"},
                {"error": "tool call rejected or failed", "error_type": "LookupError"},
            ],
        )

    def test_thread_identity_cannot_change_and_pending_thread_cannot_continue(self):
        app = CustomerSupportAgent(
            successful_delivery_model(), SupportBackend.demo(), model_id="scripted"
        )
        self.assertEqual(
            app.invoke(request("耳机没到", thread="fixed")).status, "approval_required"
        )
        with self.assertRaises(ValueError):
            app.invoke(request("再说一句", thread="fixed"))
        with self.assertRaises(ValueError):
            app.invoke(
                SupportRequest(
                    thread_id="fixed",
                    ticket_id="T-300",
                    authenticated_customer_id="C-300",
                    message="换一个身份",
                )
            )

    def test_provider_error_omits_exception_text_and_preserves_state(self):
        backend = SupportBackend.demo()
        before = backend.snapshot()
        result = CustomerSupportAgent(
            FailingModel(), backend, model_id="scripted"
        ).invoke(request("你好"))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertNotIn("provider secret detail", result.model_dump_json())
        self.assertEqual(backend.snapshot(), before)

    def test_validation_and_live_cli_fail_before_model_or_file_creation(self):
        with self.assertRaises(ValidationError):
            request("")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trace.json"
            with (
                patch(
                    "trace2flow.support_agent.deepseek_support_model",
                    side_effect=AssertionError,
                ),
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-placeholder"}),
                self.assertRaises(SystemExit),
            ):
                main(
                    [
                        "--customer-id",
                        "C-100",
                        "--ticket-id",
                        "T-100",
                        "--message",
                        "耳机没到",
                        "--trace-output",
                        str(output),
                    ]
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

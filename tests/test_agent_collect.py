"""Scripted responses test collector mechanics, not live-model task ability."""

import json
import tempfile
import unittest
from pathlib import Path

from trace2flow.agent_collect import (
    AgentTask,
    CollectionStopped,
    Collector,
    main,
    run_agent,
    save_recording,
)
from trace2flow.agent_pilot import check_development_record
from trace2flow.candidate import _require_import_review
from trace2flow.io import loads_trace_dataset

try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
except ImportError:
    BaseChatModel = None


def task(**changes):
    return AgentTask.model_validate(
        {
            "task_id": "scripted-case",
            "ticket_id": "T-TEST",
            "customer_id": "C-001",
            "order_id": "O-001",
            "ticket_text": "订单还没到，请核实并更新工单。",
            **changes,
        }
    )


def collector(**kwargs):
    return Collector(task(), model_id="scripted-test-model", scripted=True, **kwargs)


def complete_calls(instance):
    instance.dispatch("c1", "lookup_customer", {"customer_id": "C-001"})
    instance.dispatch(
        "c2", "lookup_order", {"order_id": "O-001", "customer_id": "C-001"}
    )
    instance.dispatch(
        "c3",
        "classify_issue",
        {
            "ticket_text": instance.task.ticket_text,
            "order_status": "shipped",
            "delivered": False,
            "damaged": False,
            "duplicate_charge": False,
        },
    )
    instance.dispatch(
        "c4",
        "recommend_action",
        {
            "issue_type": "delivery_delay",
            "eligible": False,
            "policy_version": "v1",
        },
    )
    instance.dispatch(
        "c5",
        "update_ticket",
        {
            "ticket_id": instance.task.ticket_id,
            "status": "pending_carrier",
            "recommendation": "carrier_investigation",
            "issue_type": "delivery_delay",
        },
    )


if BaseChatModel is not None:

    class ScriptedModel(BaseChatModel):
        responses: list[AIMessage]
        cursor: int = 0

        @property
        def _llm_type(self):
            return "scripted-collector-regression"

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            message = self.responses[self.cursor]
            self.cursor += 1
            return ChatResult(generations=[ChatGeneration(message=message)])


class CollectorTests(unittest.TestCase):
    def test_pilot_checker_detects_output_and_unrelated_state_corruption(self):
        instance = collector()
        complete_calls(instance)
        instance.ending = "model_finished"
        raw = instance.raw()
        self.assertTrue(check_development_record(raw, "delivery_delay")["passed"])
        raw["calls"][-1]["output"]["status"] = "wrong"
        result = check_development_record(raw, "delivery_delay")
        self.assertFalse(result["output_or_safe_refusal_match"])
        self.assertTrue(result["complete_state_match"])
        raw = instance.raw()
        raw["state_after"]["tickets"]["UNRELATED"]["status"] = "wrong"
        result = check_development_record(raw, "delivery_delay")
        self.assertTrue(result["output_or_safe_refusal_match"])
        self.assertFalse(result["complete_state_match"])

    def test_complete_content_types_and_unrelated_state(self):
        instance = collector()
        complete_calls(instance)
        instance.ending = "model_finished"
        data = instance.normalized()
        self.assertEqual(data.runs[0].final_output["status"], "pending_carrier")
        self.assertEqual(
            data.runs[0].final_output["recommendation"], "carrier_investigation"
        )
        self.assertIs(data.runs[0].steps[2].params["delivered"], False)
        self.assertEqual(data.runs[0].status.value, "completed")
        self.assertEqual(instance.snapshot()["tickets"]["UNRELATED"]["status"], "open")
        self.assertEqual(instance.snapshot()["orders"], instance.state_before["orders"])
        self.assertEqual(
            instance.snapshot()["customers"], instance.state_before["customers"]
        )
        self.assertFalse(data.runs[0].metadata["business_success_verified"])
        self.assertEqual(data.runs[0].provenance.kind, "synthetic")
        self.assertTrue(all(not step.depends_on for step in data.runs[0].steps))
        with self.assertRaisesRegex(ValueError, "require complete"):
            _require_import_review(data)

    def test_repeated_occurrences_kept_and_duplicate_ids_rejected(self):
        instance = collector()
        for call_id in ("a", "b"):
            instance.dispatch(call_id, "lookup_customer", {"customer_id": "C-001"})
        self.assertEqual(len(instance.normalized().runs[0].steps), 2)
        with self.assertRaises(CollectionStopped):
            instance.dispatch("a", "lookup_customer", {"customer_id": "C-001"})

    def test_unknown_tool_and_unverified_write_do_not_mutate(self):
        instance = collector()
        self.assertIn("error", instance.dispatch("a", "shell", {"code": "echo bad"}))
        self.assertIn(
            "error",
            instance.dispatch(
                "b",
                "update_ticket",
                {
                    "ticket_id": "T-TEST",
                    "status": "pending_carrier",
                    "recommendation": "carrier_investigation",
                    "issue_type": "delivery_delay",
                },
            ),
        )
        self.assertEqual(instance.snapshot(), instance.state_before)
        self.assertTrue(all(call["status"] == "failed" for call in instance.calls))

    def test_boolean_coercion_and_extra_fields_rejected(self):
        instance = collector()
        result = instance.dispatch(
            "a",
            "classify_issue",
            {
                "ticket_text": instance.task.ticket_text,
                "order_status": "shipped",
                "delivered": 0,
                "damaged": False,
                "duplicate_charge": False,
            },
        )
        self.assertEqual(result["error_type"], "ValidationError")
        result = instance.dispatch(
            "b",
            "lookup_customer",
            {
                "customer_id": "C-001",
                "arbitrary_code": "never executed",
            },
        )
        self.assertEqual(result["error_type"], "ValidationError")

    def test_foreign_order_fails_and_state_unchanged(self):
        instance = Collector(task(order_id="O-002"), model_id="scripted", scripted=True)
        result = instance.dispatch(
            "a", "lookup_order", {"order_id": "O-002", "customer_id": "C-001"}
        )
        self.assertIn("error", result)
        self.assertEqual(instance.snapshot(), instance.state_before)

    def test_wrong_facts_wrong_ticket_and_write_retry(self):
        instance = collector()
        instance.dispatch(
            "a", "lookup_order", {"order_id": "O-001", "customer_id": "C-001"}
        )
        self.assertIn(
            "error",
            instance.dispatch(
                "b",
                "classify_issue",
                {
                    "ticket_text": instance.task.ticket_text,
                    "order_status": "delivered",
                    "delivered": True,
                    "damaged": False,
                    "duplicate_charge": False,
                },
            ),
        )
        complete_calls(instance)
        before = instance.snapshot()
        for call_id, ticket in (("other", "UNRELATED"), ("retry", "T-TEST")):
            self.assertIn(
                "error",
                instance.dispatch(
                    call_id,
                    "update_ticket",
                    {
                        "ticket_id": ticket,
                        "status": "pending_carrier",
                        "recommendation": "carrier_investigation",
                        "issue_type": "delivery_delay",
                    },
                ),
            )
        self.assertEqual(instance.snapshot(), before)

    def test_tool_budget_and_no_call_recording(self):
        instance = collector(max_tool_calls=1)
        self.assertIsNone(instance.normalized())
        instance.dispatch("a", "lookup_customer", {"customer_id": "C-001"})
        with self.assertRaisesRegex(CollectionStopped, "tool_budget"):
            instance.dispatch("b", "lookup_customer", {"customer_id": "C-001"})

    def test_zero_tool_run_saves_raw_only(self):
        instance = collector()
        instance.ending = "model_finished"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "recording"
            save_recording(instance, directory)
            raw = json.loads((directory / "raw.json").read_text())
            self.assertEqual(raw["calls"], [])
            self.assertFalse((directory / "normalized.quarantine.json").exists())

    def test_exclusive_files_and_json_roundtrip(self):
        instance = collector()
        complete_calls(instance)
        instance.ending = "model_finished"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "recording"
            save_recording(instance, directory)
            raw = json.loads((directory / "raw.json").read_text())
            self.assertEqual(len(raw["calls"]), 5)
            self.assertTrue(raw["scripted_model"])
            data = loads_trace_dataset(
                (directory / "normalized.quarantine.json").read_text()
            )
            self.assertEqual(data.runs[0].final_output["status"], "pending_carrier")
            with self.assertRaises(FileExistsError):
                save_recording(instance, directory)

    def test_live_requires_explicit_flag_before_credentials_or_network(self):
        with self.assertRaises(SystemExit):
            main(["missing.json", "--output", "unused-output"])


@unittest.skipIf(
    BaseChatModel is None, "install the agent extra for offline framework regression"
)
class FrameworkTests(unittest.TestCase):
    def test_truncated_model_response_not_marked_finished(self):
        instance = collector()
        message = AIMessage(
            content="部分回答", response_metadata={"finish_reason": "length"}
        )
        run_agent(instance, ScriptedModel(responses=[message]))
        self.assertEqual(instance.ending, "incomplete_model_response")
        self.assertEqual(instance.events[-1]["finish_reason"], "length")
        self.assertEqual(instance.calls, [])

    def test_real_framework_runs_scripted_five_tool_chain(self):
        reference = collector()
        complete_calls(reference)
        responses = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": call["id"],
                        "name": call["tool"],
                        "args": call["params"],
                        "type": "tool_call",
                    }
                ],
            )
            for call in reference.calls
        ] + [AIMessage(content="已记录处理建议。")]
        instance = collector()
        run_agent(instance, ScriptedModel(responses=responses))
        self.assertEqual(instance.ending, "model_finished")
        self.assertEqual(instance.model_calls, 6)
        self.assertEqual(len(instance.calls), 5)
        self.assertEqual(
            instance.normalized().runs[0].final_output["status"], "pending_carrier"
        )
        self.assertEqual(
            len([event for event in instance.events if event["role"] == "tool"]), 5
        )

    def test_model_limit_retains_partial_calls(self):
        instance = collector(max_model_calls=1)
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "a",
                    "name": "lookup_customer",
                    "args": {"customer_id": "C-001"},
                    "type": "tool_call",
                }
            ],
        )
        run_agent(instance, ScriptedModel(responses=[message]))
        self.assertEqual(instance.ending, "model_budget_exhausted")
        self.assertEqual(len(instance.calls), 1)
        self.assertEqual(instance.normalized().runs[0].status.value, "failed")

    def test_parallel_batch_is_logged_but_not_executed(self):
        instance = collector()
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": call_id,
                    "name": "lookup_customer",
                    "args": {"customer_id": "C-001"},
                    "type": "tool_call",
                }
                for call_id in ("a", "b")
            ],
        )
        run_agent(instance, ScriptedModel(responses=[message]))
        self.assertEqual(instance.ending, "parallel_batch_requires_review")
        self.assertEqual(len(instance.events[-1]["tool_calls"]), 2)
        self.assertEqual(instance.calls, [])
        self.assertEqual(instance.snapshot(), instance.state_before)

    def test_provider_exception_message_not_recorded(self):
        instance = collector()
        run_agent(instance, ScriptedModel(responses=[]))
        self.assertEqual(instance.ending, "execution_error:IndexError")
        self.assertEqual(instance.calls, [])

    def test_independent_read_batch_runs_without_invented_dependencies(self):
        instance = collector(allow_read_batches=True)
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "a",
                    "name": "lookup_customer",
                    "args": {"customer_id": "C-001"},
                    "type": "tool_call",
                },
                {
                    "id": "b",
                    "name": "lookup_order",
                    "args": {"customer_id": "C-001", "order_id": "O-001"},
                    "type": "tool_call",
                },
            ],
        )
        run_agent(
            instance,
            ScriptedModel(responses=[message, AIMessage(content="查询结束。")]),
        )
        self.assertEqual(instance.ending, "model_finished")
        self.assertEqual(len(instance.calls), 2)
        self.assertTrue(all(call["status"] == "completed" for call in instance.calls))
        self.assertEqual(len(instance.events[1]["tool_calls"]), 2)
        self.assertTrue(
            all(not step.depends_on for step in instance.normalized().runs[0].steps)
        )
        self.assertEqual(instance.snapshot(), instance.state_before)

    def test_mixed_write_batch_rejected_even_with_read_batches_enabled(self):
        instance = collector(allow_read_batches=True)
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "a",
                    "name": "lookup_customer",
                    "args": {"customer_id": "C-001"},
                    "type": "tool_call",
                },
                {
                    "id": "b",
                    "name": "update_ticket",
                    "args": {
                        "ticket_id": "T-TEST",
                        "status": "pending_carrier",
                        "recommendation": "carrier_investigation",
                        "issue_type": "delivery_delay",
                    },
                    "type": "tool_call",
                },
            ],
        )
        run_agent(instance, ScriptedModel(responses=[message]))
        self.assertEqual(instance.ending, "parallel_batch_requires_review")
        self.assertEqual(instance.calls, [])
        self.assertEqual(instance.snapshot(), instance.state_before)

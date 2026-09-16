"""M13c predeclared paired-evaluation and freeze controls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel

from trace2flow.support_backend import SupportBackend
from trace2flow.support_evaluation import (
    PairedPlan,
    _output_correct,
    _sha,
    _state_correct,
    create_freeze,
    load_plan,
    main,
    publish_report,
    run_evaluation,
    verify_freeze,
)
from trace2flow.support_reference import reference_delivery_registration
from trace2flow.support_router import WorkflowRegistry

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "examples/customer-support-agent/m13c/plan.json"


class ExplodingModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "exploding-m13c-test-model"

    def bind_tools(self, tools, **kwargs):
        del tools, kwargs
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del messages, stop, run_manager, kwargs
        raise RuntimeError("private provider detail must not enter the report")


class SupportEvaluationTests(unittest.TestCase):
    def test_plan_is_disjoint_and_model_input_has_no_oracle(self):
        plan = load_plan(PLAN)
        self.assertFalse(
            {case.task_group_id for case in plan.cases}.intersection(
                plan.compile_task_group_ids
            )
        )
        visible = {
            "thread_id": "eval-thread",
            "ticket_id": plan.cases[0].ticket_id,
            "authenticated_customer_id": plan.cases[0].customer_id,
            "message": plan.cases[0].message,
        }
        self.assertNotIn("expected_ticket", visible)
        self.assertNotIn("expected_router_route", visible)
        self.assertNotIn("expected_answer_any", visible)

    def test_plan_rejects_compile_evaluation_overlap(self):
        payload = load_plan(PLAN).model_dump(mode="json")
        payload["compile_task_group_ids"] = [payload["cases"][0]["task_group_id"]]
        with self.assertRaisesRegex(ValueError, "overlap"):
            PairedPlan.model_validate(payload)

    def test_reference_registration_passes_runtime_gate(self):
        registry = WorkflowRegistry()
        registration = reference_delivery_registration()
        registry.register(registration)
        self.assertEqual(
            registry.get(registration.key).workflow_sha256,
            registration.workflow_sha256,
        )

    def test_state_scorer_checks_target_and_all_unrelated_state(self):
        case = load_plan(PLAN).cases[0]
        backend = SupportBackend.demo()
        before = backend.snapshot()
        backend.update_ticket(
            authenticated_customer_id=case.customer_id,
            ticket_id=case.ticket_id,
            status=case.expected_ticket.status,
            category=case.expected_ticket.category,
            summary="用于评分器测试的完整本地工单摘要。",
            idempotency_key="m13c:scorer:test",
        )
        after = backend.snapshot()
        self.assertTrue(_state_correct(before, after, case))

        backend.tickets["T-200"] = backend.tickets["T-200"].model_copy(
            update={"revision": 1}
        )
        self.assertFalse(_state_correct(before, backend.snapshot(), case))

    def test_no_write_and_output_scorers_are_predeclared(self):
        case = load_plan(PLAN).cases[-1]
        before = SupportBackend.demo().snapshot()
        self.assertTrue(_state_correct(before, before, case))
        self.assertTrue(_output_correct("无法找到该订单，请核对订单号。", case))
        self.assertFalse(_output_correct("已经退款，请核对订单号。", case))

    def test_freeze_detects_plan_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            copied_plan = directory / "plan.json"
            copied_plan.write_bytes(PLAN.read_bytes())
            freeze = directory / "freeze.json"
            create_freeze(copied_plan, freeze)
            verified, _ = verify_freeze(copied_plan, freeze)
            self.assertEqual(verified.plan_id, "m13c-synthetic-paired-v1")

            payload = json.loads(copied_plan.read_text(encoding="utf-8"))
            payload["cases"][0]["message"] += "（篡改）"
            copied_plan.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_freeze(copied_plan, freeze)

    def test_paid_evaluation_requires_both_unlock_flags(self):
        with self.assertRaises(SystemExit):
            main(["evaluate", str(PLAN), "freeze.json", "output"])

    def test_runner_retains_each_provider_failure_without_retry(self):
        plan_payload = load_plan(PLAN).model_dump(mode="json")
        plan_payload["cases"] = [plan_payload["cases"][-1]]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            plan_path = directory / "plan.json"
            plan_path.write_text(
                json.dumps(plan_payload, ensure_ascii=False), encoding="utf-8"
            )
            freeze_path = directory / "freeze.json"
            output = directory / "raw"
            create_freeze(plan_path, freeze_path)
            with (
                patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-only"}),
                patch(
                    "trace2flow.support_evaluation.deepseek_support_model",
                    return_value=ExplodingModel(),
                ),
            ):
                report = run_evaluation(plan_path, freeze_path, output)
            self.assertEqual(len(report["attempts"]), 2)
            self.assertEqual(
                [row["status"] for row in report["attempts"]],
                ["error", "error"],
            )
            self.assertEqual(len(list(output.glob("*.json"))), 3)
            self.assertNotIn(
                "private provider detail",
                (output / "report.json").read_text(encoding="utf-8"),
            )

    def test_publication_is_hash_bound_and_excludes_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            freeze = directory / "freeze.json"
            freeze.write_text("{}\n", encoding="utf-8")
            private = directory / "report.json"
            report = {
                "schema_version": "support-paired-report/1.0",
                "freeze_sha256": _sha(freeze),
                "attempts": [{"case_id": "case", "runner_error_type": None}],
            }
            private.write_text(json.dumps(report), encoding="utf-8")
            public = directory / "public.json"
            self.assertEqual(
                publish_report(private, freeze, public)["freeze_sha256"],
                _sha(freeze),
            )
            self.assertTrue(public.exists())


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from trace2flow.tau3_runner import (
    Tau3DevelopmentPlan,
    Tau3RunError,
    build_public_report,
    enforce_single_tool_call,
    load_manifest,
    load_plan,
    require_paid_call,
    verify_plan,
    write_json_exclusive,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "tau3-retail-v1"
MANIFEST = EXAMPLE / "manifest.json"
PLAN = EXAMPLE / "development-plan.json"


class Tau3RunnerTests(unittest.TestCase):
    def test_checked_in_plan_is_hash_bound_and_development_only(self):
        plan = load_plan(PLAN)
        manifest = load_manifest(MANIFEST)
        verify_plan(plan, manifest, MANIFEST)
        self.assertEqual(len(plan.tasks), 6)
        self.assertEqual(plan.max_retries, 0)
        self.assertEqual(plan.hallucination_retries, 0)
        self.assertNotIn("105", {task.task_id for task in plan.tasks})

    def test_plan_rejects_compile_task_and_manifest_tamper(self):
        plan = load_plan(PLAN)
        manifest = load_manifest(MANIFEST)
        compile_task = next(task for task in manifest.train_tasks if task.role == "compile")
        payload = plan.model_dump(mode="json")
        payload["tasks"][0] = {
            "task_id": compile_task.task_id,
            "source_task_sha256": compile_task.source_task_sha256,
            "workflow_families": compile_task.workflow_families,
        }
        with self.assertRaisesRegex(Tau3RunError, "not development-only"):
            verify_plan(Tau3DevelopmentPlan.model_validate(payload), manifest, MANIFEST)
        payload = plan.model_dump(mode="json")
        payload["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(Tau3RunError, "manifest hash mismatch"):
            verify_plan(Tau3DevelopmentPlan.model_validate(payload), manifest, MANIFEST)

    def test_duplicate_task_is_rejected(self):
        payload = load_plan(PLAN).model_dump(mode="json")
        payload["tasks"].append(payload["tasks"][0])
        with self.assertRaisesRegex(ValueError, "must be unique"):
            Tau3DevelopmentPlan.model_validate(payload)

    def test_paid_gate_fails_without_flag_or_key(self):
        with self.assertRaisesRegex(Tau3RunError, "--allow-paid-call"):
            require_paid_call(False, {})
        with self.assertRaisesRegex(Tau3RunError, "unavailable"):
            require_paid_call(True, {})
        require_paid_call(True, {"DEEPSEEK_API_KEY": "not-printed"})

    def test_multiple_tool_calls_fail_instead_of_being_truncated(self):
        one = SimpleNamespace(
            tool_calls=[SimpleNamespace(requestor="assistant", name="read")]
        )
        self.assertIs(enforce_single_tool_call(one), one)
        batch = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(requestor="assistant", name="read_one"),
                SimpleNamespace(requestor="assistant", name="read_two"),
            ]
        )
        with self.assertRaisesRegex(Tau3RunError, "multiple tool calls"):
            enforce_single_tool_call(batch)

    def test_public_report_requires_exact_inventory_and_excludes_raw_content(self):
        plan = load_plan(PLAN)
        simulations = []
        evaluator_usage = []
        for index, task in enumerate(plan.tasks):
            simulations.append(
                {
                    "id": f"private-sim-{index}",
                    "task_id": task.task_id,
                    "termination_reason": "user_stop",
                    "duration": 1.5 + index,
                    "info": None,
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "private customer content",
                            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                            "tool_calls": [
                                {
                                    "id": "secret-call-id",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "private-order"},
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "id": "secret-call-id",
                            "content": "private tool result",
                            "error": False,
                        },
                        {
                            "role": "user",
                            "content": "private user message",
                            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
                        },
                    ],
                    "reward_info": {
                        "reward": 1.0 if index == 0 else 0.0,
                        "db_check": {"db_reward": 1.0},
                        "reward_breakdown": {"NL_ASSERTION": 1.0 if index == 0 else 0.0},
                    },
                }
            )
            evaluator_usage.append(
                {"task_id": task.task_id, "prompt_tokens": 7, "completion_tokens": 1}
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.json"
            metadata = root / "metadata.json"
            results.write_text(json.dumps({"simulations": simulations}), encoding="utf-8")
            metadata.write_text(
                json.dumps(
                    {
                        "plan_sha256": __import__("hashlib").sha256(
                            PLAN.read_bytes()
                        ).hexdigest(),
                        "evaluator_usage": evaluator_usage,
                    }
                ),
                encoding="utf-8",
            )
            report = build_public_report(PLAN, MANIFEST, results, metadata)
            self.assertEqual(report["retained_results"], 6)
            self.assertEqual(report["successful_results"], 1)
            self.assertEqual(report["results"][0]["tool_call_count"], 1)
            self.assertEqual(report["results"][0]["evaluator_usage"]["calls"], 1)
            serialized = json.dumps(report)
            for forbidden in (
                "private customer content",
                "private-order",
                "secret-call-id",
                "private tool result",
            ):
                self.assertNotIn(forbidden, serialized)

            output = root / "public.json"
            write_json_exclusive(report, output)
            with self.assertRaises(FileExistsError):
                write_json_exclusive(report, output)

    def test_report_rejects_missing_planned_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.json"
            metadata = root / "metadata.json"
            results.write_text(json.dumps({"simulations": []}), encoding="utf-8")
            metadata.write_text(
                json.dumps(
                    {
                        "plan_sha256": __import__("hashlib").sha256(
                            PLAN.read_bytes()
                        ).hexdigest(),
                        "evaluator_usage": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Tau3RunError, "exactly match"):
                build_public_report(PLAN, MANIFEST, results, metadata)


if __name__ == "__main__":
    unittest.main()

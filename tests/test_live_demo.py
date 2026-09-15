"""M12 public/offline evidence and UI regressions, not a new model evaluation."""

from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from trace2flow.agent_corpus import digest
from trace2flow.live_demo import (
    ARCHIVE,
    RecordingProjection,
    binding_rows,
    failure_rows,
    load_live_demo,
    run_fresh_case,
)
from trace2flow.simulation import CustomerSupportSimulator

ROOT = Path(__file__).resolve().parents[1]


class LiveDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load_live_demo()

    def test_public_archive_needs_neither_private_recordings_nor_a_model(self):
        original_read = Path.read_bytes
        original_text = Path.read_text

        def checked_read(path, *args, **kwargs):
            self.assertNotIn("data-private", path.parts)
            self.assertNotIn(path.name, {".bashrc", ".env"})
            return original_read(path, *args, **kwargs)

        def checked_text(path, *args, **kwargs):
            self.assertNotIn("data-private", path.parts)
            self.assertNotIn(path.name, {".bashrc", ".env"})
            return original_text(path, *args, **kwargs)

        with (
            patch.object(Path, "read_bytes", checked_read),
            patch.object(Path, "read_text", checked_text),
            patch("trace2flow.agent_collect.deepseek_model", side_effect=AssertionError),
            patch("trace2flow.agent_collect.run_agent", side_effect=AssertionError),
        ):
            archive = load_live_demo()
            self.assertTrue(run_fresh_case(archive, "test-01")["correct"])

    def test_checksum_failure_blocks_mixed_or_modified_archive(self):
        for name in ("test-report.json", "artifacts/workflow.json", "recordings/test-01.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory) / "archive"
                shutil.copytree(ARCHIVE, folder)
                path = folder / name
                # Test-only mutation of a temporary copy, never the frozen fixture.
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(" ")
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    load_live_demo(folder)

    def test_changed_pipeline_is_not_presented_as_frozen(self):
        with (
            patch("trace2flow.agent_corpus.FROZEN_SOURCES", ()),
            self.assertRaisesRegex(ValueError, "implementation no longer matches"),
        ):
            load_live_demo()

    def test_recording_is_lossy_typed_and_separate_from_normalized_trace(self):
        recording = self.archive.recordings["compile-01"]
        self.assertEqual(recording.schema_version, "agent-recording-projection/1.0")
        self.assertIn("lossy", recording.projection_kind)
        self.assertFalse(recording.contains_real_customer_data)
        self.assertFalse(recording.scripted_model)
        order = next(call for call in recording.calls if call.tool == "lookup_order")
        self.assertIs(order.output["damaged"], False)
        self.assertIs(order.error_type, None)
        self.assertNotEqual(digest(False), digest(0))
        payload = recording.model_dump(mode="json")
        for name in ("events", "system_prompt", "api_key", "state_before", "headers"):
            self.assertNotIn(name, payload)
        payload["api_key"] = "test-only-rejected-placeholder"
        with self.assertRaises(ValueError):
            RecordingProjection.model_validate(payload)

    def test_repeated_failures_remain_two_distinct_occurrences(self):
        recording = self.archive.recordings["compile-10"]
        orders = [call for call in recording.calls if call.tool == "lookup_order"]
        self.assertEqual(len(orders), 2)
        self.assertEqual({call.status for call in orders}, {"failed"})
        self.assertEqual({call.error_type for call in orders}, {"ValueError"})
        self.assertEqual(len({call.id for call in orders}), 2)
        self.assertNotIn("compile-10", {
            run.inputs["task_id"] for run in self.archive.compile_dataset.runs
        })
        self.assertIn("compile-10", {
            item["case_id"] for item in self.archive.reports["compile"]["agent"]["results"]
        })

    def test_zero_call_record_is_kept_without_invented_step(self):
        recording = self.archive.recordings["test-11"]
        self.assertEqual(recording.calls, [])
        self.assertEqual(recording.model_calls, 1)
        self.assertIsNone(recording.task.customer_id)
        rows = failure_rows(self.archive)
        zero = next(row for row in rows if row["任务"] == "test-11")
        self.assertEqual(zero["工具调用"], 0)
        self.assertEqual(sum(row["失败工具调用"] for row in rows), 10)

    def test_dag_evidence_links_exact_compile_occurrences_not_call_order(self):
        workflow = self.archive.workflow
        tools = {node.id: node.tool for node in workflow.nodes}
        self.assertEqual(len(workflow.edges), 3)
        self.assertNotIn(("lookup_customer", "lookup_order"), {
            (tools[edge.source_node_id], tools[edge.target_node_id])
            for edge in workflow.edges
        })
        original = {
            f"{run.id}:{step.id}"
            for run in self.archive.compile_dataset.runs for step in run.steps
        }
        for edge in workflow.edges:
            self.assertEqual(len(edge.evidence), 9)
            for evidence in edge.evidence:
                self.assertIn(evidence.source_occurrence_id, original)
                self.assertIn(evidence.target_occurrence_id, original)
        rows = binding_rows(workflow)
        self.assertEqual(sum(row["绑定类别"] == "task_input" for row in rows), 6)
        self.assertEqual(sum(row["绑定类别"] == "tool_output" for row in rows), 9)
        self.assertEqual({row["观测证据数"] for row in rows}, {9})
        policy = next(row for row in rows if row["参数"] == "policy_version")
        self.assertEqual(policy["声明来源"], "task.policy_version")

    def test_fresh_execution_has_real_outputs_and_exact_whole_state_diff(self):
        result = run_fresh_case(self.archive, "test-01")
        self.assertTrue(result["correct"])
        self.assertTrue(result["output_match"])
        self.assertTrue(result["complete_state_match"])
        self.assertEqual(len(result["outputs"]), 5)
        self.assertEqual(result["actual_final_output"]["status"], "pending_carrier")
        self.assertEqual(len(result["actual_changes"]), 3)
        self.assertEqual({item["path"][0] for item in result["actual_changes"]}, {"tickets"})
        self.assertEqual(result["model_calls"], 0)
        self.assertFalse(result["recorded_response_replay_used"])
        # Mutating one returned state cannot pollute the next independent execution.
        result["actual_state_after"]["customers"].clear()
        again = run_fresh_case(self.archive, "test-01")
        self.assertTrue(again["correct"])
        self.assertTrue(again["actual_state_after"]["customers"])

    def test_all_known_cases_reproduce_archived_admission_without_rescoring_model(self):
        expected = self.archive.reports["test"]["workflow"]
        results = [run_fresh_case(self.archive, item["case_id"]) for item in expected["results"]]
        self.assertEqual(sum(item["admitted"] for item in results), 8)
        self.assertEqual(sum(item["correct"] for item in results), 12)
        for actual, historical in zip(results, expected["results"], strict=True):
            for key in ("admitted", "correct", "output_match", "complete_state_match"):
                self.assertEqual(actual[key], historical[key])
            self.assertEqual(actual["scope"], "known_archived_case_fresh_local_regression")
        self.assertEqual(expected["coverage"], 8 / 12)
        self.assertEqual(expected["accepted_case_correctness"], 1)

    def test_refusal_does_not_run_tools_and_does_not_mutate_any_state(self):
        with patch.object(CustomerSupportSimulator, "lookup_customer", side_effect=AssertionError):
            for case in ("test-08", "test-09", "test-10", "test-11"):
                result = run_fresh_case(self.archive, case)
                self.assertTrue(result["correct"])
                self.assertFalse(result["admitted"])
                self.assertTrue(result["refusal_reason"])
                self.assertEqual(result["outputs"], {})
                self.assertEqual(result["actual_changes"], [])
                self.assertEqual(result["actual_state_after"], result["state_before"])

    def test_corrupt_tool_output_is_not_replaced_with_expected_result(self):
        with patch.object(CustomerSupportSimulator, "update_ticket", return_value={"wrong": True}):
            result = run_fresh_case(self.archive, "test-01")
        self.assertFalse(result["correct"])
        self.assertFalse(result["output_match"])
        self.assertFalse(result["complete_state_match"])
        self.assertEqual(result["actual_final_output"], {"wrong": True})

    def test_unrelated_customer_mutation_fails_full_state_check(self):
        original = CustomerSupportSimulator.lookup_customer

        def mutate(simulator, customer_id):
            output = original(simulator, customer_id)
            simulator.customers[customer_id]["unexpected_mutation"] = True
            return output

        with patch.object(CustomerSupportSimulator, "lookup_customer", mutate):
            result = run_fresh_case(self.archive, "test-01")
        self.assertTrue(result["output_match"])
        self.assertFalse(result["complete_state_match"])
        self.assertFalse(result["correct"])
        self.assertIn("customers", {item["path"][0] for item in result["actual_changes"]})

    def test_tool_exception_remains_failure_without_exception_text_leakage(self):
        with patch.object(CustomerSupportSimulator, "recommend_action", side_effect=RuntimeError("private text")):
            result = run_fresh_case(self.archive, "test-01")
        self.assertFalse(result["correct"])
        self.assertEqual(result["error"], "RuntimeError")
        self.assertNotIn("private text", json.dumps(result))

    def test_unknown_case_compile_case_and_unknown_tool_cannot_execute(self):
        for case in ("../../private", "compile-01"):
            with self.assertRaises(ValueError):
                run_fresh_case(self.archive, case)
        workflow = self.archive.workflow.model_copy(deep=True)
        workflow.nodes[0].tool = "arbitrary_shell"
        result = run_fresh_case(replace(self.archive, workflow=workflow), "test-01")
        self.assertFalse(result["admitted"])
        self.assertFalse(result["correct"])
        self.assertEqual(result["outputs"], {})


class LiveDemoUITests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=15).run()

    def test_default_ui_shows_separate_coverage_correctness_and_scope(self):
        app = self.app()
        self.assertEqual(app.exception, [])
        self.assertEqual([item.value for item in app.metric], ["8/12", "8/8", "4", "40 → 0"])
        rendered = "\n".join(item.value for items in (
            app.caption, app.warning, app.markdown,
        ) for item in items)
        for claim in ("AI 显式审核", "没有人工审核", "合成业务状态", "不是新 holdout", "40 → 40"):
            self.assertIn(claim, rendered)

    def test_ui_executes_success_then_refuses_without_showing_stale_result(self):
        app = self.app()
        app.button(key="live_execute").click().run()
        self.assertEqual(app.exception, [])
        self.assertTrue(any("执行 5 个节点" in item.value for item in app.success))
        app.selectbox(key="live_case").set_value("test-11").run()
        self.assertEqual(app.success, [])
        app.button(key="live_execute").click().run()
        self.assertEqual(app.exception, [])
        self.assertTrue(any("安全拒绝" in item.value for item in app.success))
        self.assertTrue(any("全部保持不变" in item.value for item in app.info))

    def test_ui_exposes_repeated_failures_and_zero_call_without_fake_steps(self):
        app = self.app()
        app.selectbox(key="live_recording").set_value("compile-10").run()
        self.assertEqual(app.exception, [])
        calls = [json.loads(item.value) for item in app.json if '"error_type"' in item.value]
        orders = [call for call in calls if call.get("tool") == "lookup_order"]
        self.assertEqual(len(orders), 2)
        self.assertEqual(len({call["id"] for call in orders}), 2)
        app.selectbox(key="live_recording").set_value("test-11").run()
        self.assertEqual(app.exception, [])
        self.assertTrue(any("calls=[]" in item.value for item in app.info))
        self.assertFalse(any('"error_type"' in item.value for item in app.json))

    def test_ui_stops_on_corrupt_archive_and_does_not_show_scores(self):
        with patch("trace2flow.live_demo_ui.load_live_demo", side_effect=ValueError):
            app = self.app()
        self.assertEqual(app.exception, [])
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any("归档校验失败" in item.value for item in app.error))

    def test_safe_rendering_and_no_dynamic_code_or_collector_calls(self):
        for path in (ROOT / "streamlit_app.py", ROOT / "src/trace2flow/live_demo_ui.py"):
            source = path.read_text()
            tree = ast.parse(source)
            calls = {
                getattr(node.func, "attr", getattr(node.func, "id", ""))
                for node in ast.walk(tree) if isinstance(node, ast.Call)
            }
            self.assertTrue({"html", "eval", "exec", "run_agent", "deepseek_model"}.isdisjoint(calls))
            self.assertNotIn("unsafe_allow_html", source)


if __name__ == "__main__":
    unittest.main()

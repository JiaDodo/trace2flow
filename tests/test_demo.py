"""Smoke coverage for the pure demo pipeline and Streamlit presentation."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from streamlit.testing.v1 import AppTest

from trace2flow.demo import (
    build_demo_artifacts,
    candidate_dot,
    default_demo_texts,
    downloadable_json,
    evidence_rows,
)


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifacts = build_demo_artifacts(*default_demo_texts())

    def test_default_demo_builds_all_downloadable_artifacts(self) -> None:
        artifacts = self.artifacts
        self.assertEqual(len(artifacts.candidate.nodes), 5)
        self.assertEqual(len(artifacts.candidate.edges), 5)
        self.assertEqual(artifacts.workflow.execution_blockers(), [])
        self.assertIsNotNone(artifacts.prefect)
        self.assertIsNotNone(artifacts.verification)
        self.assertTrue(artifacts.verification.passed)

        downloads = downloadable_json(artifacts)
        self.assertEqual(
            set(downloads),
            {"candidate.json", "workflow.json", "verification.json"},
        )
        self.assertTrue(all(content.endswith("\n") for content in downloads.values()))

    def test_dag_and_every_accepted_dependency_evidence_are_presentable(self) -> None:
        dot = candidate_dot(self.artifacts.candidate)
        rows = evidence_rows(self.artifacts.candidate)

        self.assertTrue(dot.startswith("digraph trace2flow"))
        self.assertEqual(dot.count(" evidence\"") , 5)
        self.assertEqual(len(rows), 15)
        self.assertEqual({row["status"] for row in rows}, {"accepted"})
        self.assertEqual(
            {row["run_id"] for row in rows},
            {
                "compile_delivery_delay",
                "compile_billing_duplicate",
                "compile_damaged_item",
            },
        )

    def test_streamlit_app_smoke_runs_default_pipeline(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=15).run()
        self.assertEqual(app.exception, [])
        self.assertEqual(app.title[0].value, "Trace2Flow · Agent 轨迹到可验证工作流")
        self.assertEqual(len(app.file_uploader), 2)
        self.assertEqual(len(app.text_area), 1)

        app.button[0].click().run(timeout=20)
        self.assertEqual(app.exception, [])
        self.assertEqual([metric.value for metric in app.metric], ["5", "5", "0", "通过"])
        self.assertTrue(
            any("独立本地模拟验证通过" in item.value for item in app.success)
        )

    def test_changed_upload_falls_back_to_inspectable_unresolved_ir(self) -> None:
        compile_text, resolution_text, _ = default_demo_texts()
        payload = json.loads(compile_text)
        for run in payload["runs"]:
            run["steps"][0]["params"]["new_optional_field"] = None
        artifacts = build_demo_artifacts(
            json.dumps(payload),
            resolution_text,
            allow_unresolved_fallback=True,
        )

        self.assertIsNotNone(artifacts.resolution_error)
        self.assertEqual(len(artifacts.candidate.nodes), 5)
        self.assertGreater(len(artifacts.workflow.execution_blockers()), 0)
        self.assertIsNone(artifacts.prefect)
        self.assertIsNone(artifacts.verification)

    def test_ui_does_not_render_unsafe_html_or_evaluate_uploads(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        attribute_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue({"html", "eval", "exec"}.isdisjoint(attribute_calls))
        self.assertNotIn("unsafe_allow_html", source)


if __name__ == "__main__":
    unittest.main()

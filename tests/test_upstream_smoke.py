"""Content-level smoke test for the verified upstream CLI pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAIN_TRACES = ROOT / "tests" / "fixtures" / "smoke_train.lp"
HOLDOUT_TRACES = ROOT / "tests" / "fixtures" / "smoke_holdout.json"
RULES = ROOT / "rules" / "mine_patterns.lp"


class UpstreamPipelineSmokeTest(unittest.TestCase):
    """Exercise compile -> benchmark -> both code generation targets."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tempdir = tempfile.TemporaryDirectory(prefix="trace2flow-smoke-")
        cls.tempdir = Path(cls._tempdir.name)
        cls.compiled_path = cls.tempdir / "compiled.json"

        cls.compile_result = cls.run_cli(
            "src/compile.py",
            "--traces",
            str(TRAIN_TRACES),
            "--rules",
            str(RULES),
            "--output",
            str(cls.compiled_path),
        )
        cls.compiled = json.loads(cls.compiled_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tempdir.cleanup()

    @classmethod
    def run_cli(cls, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, script, *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_compile_mines_expected_structure_and_parameters(self) -> None:
        metadata = self.compiled["_autocompile"]
        self.assertEqual(metadata["source_runs"], 3)
        self.assertEqual(
            set(metadata["core_tools"]), {"lookup_customer", "update_ticket"}
        )
        self.assertEqual(
            metadata["phases"],
            {"0": ["lookup_customer"], "1": ["update_ticket"]},
        )

        calls = {call["tool"]: call for call in self.compiled["calls"]}
        self.assertEqual(calls["lookup_customer"]["input"], {"source": "support_fixture"})
        self.assertEqual(calls["update_ticket"]["input"], {"status": "resolved"})
        self.assertEqual(
            calls["update_ticket"]["waits_for"],
            [calls["lookup_customer"]["id"]],
        )
        self.assertEqual(
            self.compiled["_analysis"]["variable_params"],
            {
                "lookup_customer": ["customer_id"],
                "update_ticket": ["ticket_id"],
            },
        )
        self.assertIn("PATTERN MINING RESULTS (3 runs analyzed)", self.compile_result.stdout)

    def test_benchmark_reports_expected_content_on_disjoint_holdout(self) -> None:
        result = self.run_cli(
            "src/benchmark.py",
            "--compiled",
            str(self.compiled_path),
            "--holdout",
            str(HOLDOUT_TRACES),
        )
        self.assertIn("Holdout runs: 2", result.stdout)
        self.assertIn("Tool accuracy: 100%", result.stdout)
        self.assertIn("Param accuracy: 100%", result.stdout)
        self.assertIn("Runs where compiled DAG matched: 2/2 (100%)", result.stdout)

    def test_codegen_emits_expected_pseudo_and_daslab_content(self) -> None:
        pseudo = self.run_cli(
            "src/codegen.py",
            "--compiled",
            str(self.compiled_path),
            "--target",
            "pseudo",
        ).stdout
        self.assertIn("synthesized from 3 observed runs", pseudo)
        self.assertIn("# --- Phase 0 ---", pseudo)
        self.assertIn("lookup_customer(source='support_fixture')", pseudo)
        self.assertIn("update_ticket(status='resolved')", pseudo)

        job_path = self.tempdir / "job.json"
        self.run_cli(
            "src/codegen.py",
            "--compiled",
            str(self.compiled_path),
            "--target",
            "daslab",
            "--output",
            str(job_path),
        )
        job = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(job["_source"]["source_runs"], 3)
        calls = {call["tool"]: call for call in job["calls"]}
        self.assertEqual(calls["lookup_customer"]["input"], {"source": "support_fixture"})
        self.assertEqual(calls["lookup_customer"]["_runtime_params"], ["customer_id"])
        self.assertEqual(calls["update_ticket"]["input"], {"status": "resolved"})
        self.assertEqual(calls["update_ticket"]["_runtime_params"], ["ticket_id"])
        self.assertEqual(
            calls["update_ticket"]["waits_for"],
            [calls["lookup_customer"]["id"]],
        )


if __name__ == "__main__":
    unittest.main()

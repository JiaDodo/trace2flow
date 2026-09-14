"""End-to-end tests for the local normalized-trace CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"


class TraceCliTest(unittest.TestCase):
    @staticmethod
    def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "trace2flow", *args],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_validate_reports_content_and_writes_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            output = Path(tempdir) / "normalized.json"
            result = self.run_cli("validate", str(FIXTURE), "--output", str(output))
            summary = json.loads(result.stdout)

            self.assertEqual(
                summary,
                {
                    "dataset_id": "synthetic_customer_support_m1",
                    "partition": "compile",
                    "runs": 3,
                    "steps": 18,
                    "valid": True,
                },
            )
            self.assertTrue(output.read_text(encoding="utf-8").endswith("\n"))

    def test_split_and_to_asp_write_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace2flow-cli-test-") as tempdir:
            root = Path(tempdir)
            compile_path = root / "compile.json"
            test_path = root / "test.json"
            asp_path = root / "compile.lp"

            split = self.run_cli(
                "split",
                str(FIXTURE),
                "--test-run-id",
                "support_run_3",
                "--compile-output",
                str(compile_path),
                "--test-output",
                str(test_path),
            )
            self.assertEqual(
                json.loads(split.stdout),
                {"compile_runs": 2, "test_runs": 1},
            )

            adapted = self.run_cli(
                "to-asp",
                str(compile_path),
                "--output",
                str(asp_path),
            )
            self.assertEqual(json.loads(adapted.stdout)["runs"], 2)
            facts = asp_path.read_text(encoding="utf-8")
            self.assertIn('job("support_run_1")', facts)
            self.assertNotIn('job("support_run_3")', facts)


if __name__ == "__main__":
    unittest.main()

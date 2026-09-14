"""Tests for the typed boundary around the upstream ASP compiler."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.asp import (
    PARAM_ENCODING,
    decode_json_value,
    encode_json_value,
    to_asp,
)
from trace2flow.io import canonical_json, load_trace_dataset

FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"


class AspAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_trace_dataset(FIXTURE)

    def test_parameter_encoding_round_trips_without_scalar_collisions(self) -> None:
        values = [None, False, True, 0, 1, 1.0, "1", [1, True, None], {"b": 1, "a": False}]
        encoded = [encode_json_value(value) for value in values]
        decoded = [decode_json_value(value) for value in encoded]

        self.assertEqual(len(encoded), len(set(encoded)))
        self.assertEqual(decoded, values)
        self.assertIs(type(decoded[4]), int)
        self.assertIs(type(decoded[5]), float)
        self.assertTrue(all(value.startswith("json_b64:") for value in encoded))

    def test_adapter_retains_occurrences_and_typed_source_snapshot(self) -> None:
        before = canonical_json(self.dataset)
        bundle = to_asp(self.dataset)

        self.assertEqual(bundle.parameter_encoding, PARAM_ENCODING)
        self.assertEqual(canonical_json(bundle.source), before)
        self.assertEqual(len(bundle.source_sha256), 64)
        self.assertEqual(bundle.facts.count('"lookup_order", "completed"'), 6)
        self.assertIn('call("support_run_1", "lookup_order_1"', bundle.facts)
        self.assertIn('call("support_run_1", "lookup_order_2"', bundle.facts)
        self.assertIn("parameter_encoding=canonical-json-base64url-v1", bundle.facts)

        run = bundle.source.run_by_id("support_run_1")
        first_order = next(step for step in run.steps if step.id == "lookup_order_1")
        self.assertIs(type(first_order.params["order_id"]), int)
        self.assertIs(type(first_order.output["delivered"]), bool)

    def test_generated_facts_compile_with_pinned_upstream_entry_point(self) -> None:
        bundle = to_asp(self.dataset)
        with tempfile.TemporaryDirectory(prefix="trace2flow-asp-test-") as tempdir:
            temp_path = Path(tempdir)
            facts_path = temp_path / "traces.lp"
            output_path = temp_path / "compiled.json"
            bundle.write(facts_path)

            result = subprocess.run(
                [
                    sys.executable,
                    "src/compile.py",
                    "--traces",
                    str(facts_path),
                    "--rules",
                    "rules/mine_patterns.lp",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            compiled = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(compiled["_autocompile"]["source_runs"], 3)
            self.assertEqual(
                set(compiled["_autocompile"]["core_tools"]),
                {
                    "lookup_customer",
                    "lookup_order",
                    "classify_issue",
                    "recommend_action",
                    "update_ticket",
                },
            )
            self.assertIn("Written to", result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertEqual(canonical_json(bundle.source), canonical_json(self.dataset))


if __name__ == "__main__":
    unittest.main()

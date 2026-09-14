"""Tests for strict, type-preserving normalized trace ingestion."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.io import (
    TraceFormatError,
    canonical_json,
    load_trace_dataset,
    loads_trace_dataset,
)

FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"


class TraceModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_json_types_and_repeated_call_occurrences_are_preserved(self) -> None:
        dataset = load_trace_dataset(FIXTURE)
        run = dataset.run_by_id("support_run_1")

        self.assertIs(type(run.inputs["priority"]), int)
        self.assertIs(type(run.inputs["expedited"]), bool)
        self.assertIsNone(run.inputs["coupon"])
        self.assertEqual(run.inputs["tags"], ["delivery", "new-customer"])

        classify = next(step for step in run.steps if step.id == "classify_issue_1")
        self.assertIs(type(classify.params["urgency"]), int)
        self.assertIs(type(classify.params["eligible"]), bool)
        self.assertIsNone(classify.params["missing_value"])
        self.assertEqual(
            classify.params["signals"],
            {"order_ids": [1001, 1002], "urgent": False},
        )

        order_calls = [step for step in run.steps if step.tool == "lookup_order"]
        self.assertEqual([step.id for step in order_calls], ["lookup_order_1", "lookup_order_2"])
        self.assertIn("support_run_1:lookup_order_1", run.occurrence_ids())
        self.assertIn("support_run_1:lookup_order_2", run.occurrence_ids())

    def test_canonical_round_trip_is_deterministic(self) -> None:
        dataset = load_trace_dataset(FIXTURE)
        normalized = canonical_json(dataset)
        reordered_input = json.dumps(self.raw, ensure_ascii=False, sort_keys=False)

        self.assertEqual(normalized, canonical_json(loads_trace_dataset(reordered_input)))
        self.assertEqual(dataset, loads_trace_dataset(normalized))
        self.assertIn('"expedited": false', normalized)
        self.assertIn('"coupon": null', normalized)

        with tempfile.TemporaryDirectory(prefix="trace2flow-model-test-") as tempdir:
            path = Path(tempdir) / "normalized.json"
            path.write_text(normalized, encoding="utf-8")
            self.assertEqual(dataset, load_trace_dataset(path))

    def test_invalid_reference_has_stable_location_and_message(self) -> None:
        self.raw["runs"][0]["steps"][1]["depends_on"] = ["missing_step"]
        with self.assertRaisesRegex(
            TraceFormatError,
            r"runs\.0: Value error, step 'lookup_order_1' references unknown step\(s\): missing_step",
        ):
            loads_trace_dataset(json.dumps(self.raw))

    def test_duplicate_occurrence_id_and_cycles_are_rejected(self) -> None:
        duplicate = json.loads(json.dumps(self.raw))
        duplicate["runs"][0]["steps"][2]["id"] = "lookup_order_1"
        with self.assertRaisesRegex(TraceFormatError, "duplicate step ids: lookup_order_1"):
            loads_trace_dataset(json.dumps(duplicate))

        cyclic = json.loads(json.dumps(self.raw))
        cyclic["runs"][0]["steps"][0]["depends_on"] = ["update_ticket_1"]
        with self.assertRaisesRegex(TraceFormatError, "dependency cycle includes step"):
            loads_trace_dataset(json.dumps(cyclic))

    def test_non_json_numbers_duplicate_keys_and_extra_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(TraceFormatError, "non-finite JSON number"):
            loads_trace_dataset(
                '{"schema_version":"1.0","dataset_id":"x","runs":NaN}'
            )
        with self.assertRaisesRegex(TraceFormatError, "duplicate JSON object key: x"):
            loads_trace_dataset('{"x":1,"x":2}')

        self.raw["unexpected"] = "not allowed"
        with self.assertRaisesRegex(TraceFormatError, "unexpected: Extra inputs are not permitted"):
            loads_trace_dataset(json.dumps(self.raw))


if __name__ == "__main__":
    unittest.main()

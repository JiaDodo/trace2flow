"""Tests for complete-run splitting and leakage detection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.datasets import (
    DatasetLeakageError,
    assert_disjoint,
    split_by_test_run_ids,
)
from trace2flow.io import load_trace_dataset
from trace2flow.models import DatasetPartition

FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"


class DatasetBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = load_trace_dataset(FIXTURE)

    def test_split_moves_only_complete_runs_and_marks_partitions(self) -> None:
        split = split_by_test_run_ids(self.dataset, ["support_run_3"])

        self.assertEqual(split.compile.partition, DatasetPartition.COMPILE)
        self.assertEqual(split.test.partition, DatasetPartition.TEST)
        self.assertEqual(
            [run.id for run in split.compile.runs],
            ["support_run_1", "support_run_2"],
        )
        self.assertEqual([run.id for run in split.test.runs], ["support_run_3"])
        self.assertEqual(len(split.test.runs[0].steps), 6)
        self.assertEqual(
            split.compile.metadata["parent_dataset_id"], self.dataset.dataset_id
        )
        assert_disjoint(split.compile, split.test)

    def test_overlap_by_run_id_is_rejected(self) -> None:
        compile_data = self.dataset.model_copy(
            update={"runs": [self.dataset.runs[0]]}, deep=True
        )
        test_data = self.dataset.model_copy(
            update={"runs": [self.dataset.runs[0]]}, deep=True
        )
        with self.assertRaisesRegex(DatasetLeakageError, "overlapping run ids"):
            assert_disjoint(compile_data, test_data)

    def test_renamed_run_with_same_provenance_is_rejected(self) -> None:
        original = self.dataset.runs[0]
        renamed = original.model_copy(update={"id": "renamed_copy"}, deep=True)
        compile_data = self.dataset.model_copy(update={"runs": [original]}, deep=True)
        test_data = self.dataset.model_copy(update={"runs": [renamed]}, deep=True)

        with self.assertRaisesRegex(
            DatasetLeakageError, "overlapping run provenance fingerprints"
        ):
            assert_disjoint(compile_data, test_data)

    def test_invalid_explicit_split_is_rejected(self) -> None:
        with self.assertRaisesRegex(KeyError, "unknown test run ids: missing"):
            split_by_test_run_ids(self.dataset, ["missing"])
        with self.assertRaisesRegex(ValueError, "compile partition cannot be empty"):
            split_by_test_run_ids(
                self.dataset,
                [run.id for run in self.dataset.runs],
            )


if __name__ == "__main__":
    unittest.main()

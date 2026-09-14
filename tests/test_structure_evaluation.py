"""Tests for held-out structure coverage without execution overclaiming."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.candidate import mine_candidate_dag
from trace2flow.datasets import split_by_test_group_ids
from trace2flow.evaluation import evaluate_structure
from trace2flow.models import DatasetPartition, TraceDataset
from trace2flow.tau_import import import_tau_results, load_tau_results, load_tau_review

RESULTS = ROOT / "tests" / "fixtures" / "tau_retail_results.json"
REVIEW = ROOT / "tests" / "fixtures" / "tau_retail_review.json"


class StructureEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        dataset = import_tau_results(
            load_tau_results(RESULTS),
            dataset_id="structure_evaluation_fixture",
            review=load_tau_review(REVIEW),
        )
        self.split = split_by_test_group_ids(
            dataset, ["address-change-holdout"]
        )
        self.candidate = mine_candidate_dag(self.split.compile)

    def test_disjoint_holdout_structure_is_covered_without_execution_claim(self) -> None:
        report = evaluate_structure(
            self.candidate, self.split.compile, self.split.test
        )

        self.assertTrue(report.all_runs_structurally_covered)
        self.assertEqual(report.covered_runs, 1)
        self.assertEqual(report.candidate_nodes, 3)
        self.assertEqual(report.candidate_edges, 2)
        self.assertFalse(report.execution_equivalence_claimed)
        self.assertEqual(report.validation_scope, "held_out_structure_only")
        self.assertEqual(report.run_results[0].matched_occurrences, 3)
        self.assertEqual(len(report.run_results[0].supported_candidate_edge_ids), 2)

    def test_unseen_holdout_tool_is_reported_not_silently_accepted(self) -> None:
        payload = self.split.test.model_dump(mode="python")
        payload["runs"][0]["steps"][1]["tool"] = "unseen_order_lookup"
        changed = TraceDataset.model_validate(payload)

        report = evaluate_structure(self.candidate, self.split.compile, changed)

        self.assertFalse(report.all_runs_structurally_covered)
        result = report.run_results[0]
        self.assertEqual(result.matched_occurrences, 2)
        self.assertEqual(len(result.unmatched_occurrences), 1)
        self.assertGreaterEqual(len(result.missing_candidate_edge_ids), 1)

    def test_candidate_content_mismatch_is_rejected(self) -> None:
        payload = self.split.compile.model_dump(mode="python")
        payload["metadata"]["tampered"] = True
        changed_compile = TraceDataset.model_validate(payload)

        with self.assertRaisesRegex(ValueError, "different compile dataset content"):
            evaluate_structure(self.candidate, changed_compile, self.split.test)

    def test_unreviewed_holdout_is_rejected(self) -> None:
        unreviewed = import_tau_results(
            load_tau_results(RESULTS),
            dataset_id="unreviewed_holdout",
            task_ids=["address-change-holdout"],
        ).model_copy(update={"partition": DatasetPartition.TEST}, deep=True)

        with self.assertRaisesRegex(ValueError, "test traces require complete"):
            evaluate_structure(self.candidate, self.split.compile, unreviewed)


if __name__ == "__main__":
    unittest.main()

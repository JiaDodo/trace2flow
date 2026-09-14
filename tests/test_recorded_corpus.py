"""Reproducibility and claim-boundary checks for the recorded tau corpus."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.candidate import CandidateDag, candidate_json, mine_candidate_dag
from trace2flow.datasets import assert_disjoint
from trace2flow.evaluation import evaluate_structure, structural_report_json
from trace2flow.io import load_trace_dataset

CORPUS = ROOT / "examples" / "tau-retail-recorded"


class RecordedCorpusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.compile = load_trace_dataset(CORPUS / "compile.json")
        self.test = load_trace_dataset(CORPUS / "holdout.json")

    def test_corpus_is_recorded_simulation_with_disjoint_task_entities(self) -> None:
        assert_disjoint(self.compile, self.test)
        self.assertEqual(len(self.compile.runs), 3)
        self.assertEqual(len(self.test.runs), 4)
        self.assertEqual(
            {run.provenance.task_group_id for run in self.compile.runs}, {"44"}
        )
        self.assertEqual(
            {run.provenance.task_group_id for run in self.test.runs}, {"60"}
        )
        for run in [*self.compile.runs, *self.test.runs]:
            self.assertEqual(run.provenance.kind, "recorded")
            self.assertEqual(
                run.provenance.execution_context, "benchmark_simulator"
            )
            self.assertFalse(run.provenance.contains_real_customer_data)
            self.assertEqual(
                run.provenance.source_revision,
                "ade39493be54aad326a4c65295f77fe09780329b",
            )
            self.assertEqual(len(run.steps), 4)
            self.assertTrue(all(isinstance(step.output, str) for step in run.steps))

    def test_selection_matches_committed_source_run_ids(self) -> None:
        selection = json.loads(
            (CORPUS / "selection.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {run.provenance.source_run_id for run in self.compile.runs},
            set(selection["compile"]["simulation_ids"]),
        )
        self.assertEqual(
            {run.provenance.source_run_id for run in self.test.runs},
            set(selection["test"]["simulation_ids"]),
        )
        self.assertEqual(
            selection["source"]["result_sha256"],
            "6d6badb43b716adca31591b0b40e15fd493b49adddaa8e2c47035bb557549257",
        )

    def test_redacted_artifacts_exclude_reviewed_identifiers_and_provider_data(self) -> None:
        serialized = (CORPUS / "compile.json").read_text(encoding="utf-8") + (
            CORPUS / "holdout.json"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "Aarav",
            "Anderson",
            "Chen Johnson",
            "19031",
            "77004",
            "W9300146",
            "W5061109",
            "6817146515",
            "9924732112",
            "9190635437",
            "3694871183",
            "gift_card_7245904",
            "paypal_3742148",
            '"raw_data"',
            '"usage"',
            '"timestamp"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_candidate_and_structural_report_are_exactly_reproducible(self) -> None:
        committed_candidate = CandidateDag.model_validate_json(
            (CORPUS / "candidate.json").read_text(encoding="utf-8")
        )
        reproduced_candidate = mine_candidate_dag(self.compile)
        self.assertEqual(
            candidate_json(reproduced_candidate), candidate_json(committed_candidate)
        )

        report = evaluate_structure(
            committed_candidate, self.compile, self.test
        )
        self.assertEqual(
            structural_report_json(report),
            (CORPUS / "structural-report.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(report.covered_runs, 4)
        self.assertTrue(report.all_runs_structurally_covered)
        self.assertFalse(report.execution_equivalence_claimed)


if __name__ == "__main__":
    unittest.main()

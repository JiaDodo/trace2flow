"""Regression tests for conservative tau retail trace ingestion."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.candidate import mine_candidate_dag
from trace2flow.datasets import (
    DatasetLeakageError,
    assert_disjoint,
    split_by_test_group_ids,
)
from trace2flow.io import canonical_json
from trace2flow.models import DatasetPartition
from trace2flow.tau_import import (
    TauImportError,
    import_tau_results,
    load_tau_results,
    load_tau_review,
)

RESULTS = ROOT / "tests" / "fixtures" / "tau_retail_results.json"
REVIEW = ROOT / "tests" / "fixtures" / "tau_retail_review.json"


class TauImportTest(unittest.TestCase):
    def test_unreviewed_import_is_redacted_typed_and_not_mineable(self) -> None:
        dataset = import_tau_results(
            load_tau_results(RESULTS),
            dataset_id="tau_quarantine",
            task_ids=["address-change"],
            successful_only=True,
        )

        self.assertEqual(len(dataset.runs), 2)
        self.assertEqual(dataset.metadata["import_review_status"], "required")
        self.assertEqual(dataset.partition, DatasetPartition.UNSPECIFIED)
        run = dataset.runs[0]
        self.assertEqual(run.provenance.kind, "recorded")
        self.assertEqual(run.provenance.execution_context, "benchmark_simulator")
        self.assertFalse(run.provenance.contains_real_customer_data)
        self.assertEqual(run.provenance.task_group_id, "address-change")
        self.assertEqual([step.depends_on for step in run.steps], [[], [], []])
        self.assertEqual(run.steps[0].params["retry"], 1)
        self.assertIs(run.steps[0].params["active"], True)
        self.assertIsNone(run.steps[0].params["note"])
        self.assertIsInstance(run.steps[1].output, str)

        serialized = canonical_json(dataset)
        for forbidden in (
            "Ada",
            "Example",
            "10001",
            "#W100",
            "W100",
            "12 Main Street",
            "secret_provider_payload",
            "prompt_tokens",
        ):
            self.assertNotIn(forbidden, serialized)

        compile_data = dataset.model_copy(
            update={"partition": DatasetPartition.COMPILE}, deep=True
        )
        with self.assertRaisesRegex(ValueError, "require complete dependency"):
            mine_candidate_dag(compile_data)

    def test_complete_review_adds_only_declared_semantics(self) -> None:
        dataset = import_tau_results(
            load_tau_results(RESULTS),
            dataset_id="tau_reviewed",
            simulation_ids=["sim-address-1"],
            review=load_tau_review(REVIEW),
        )

        self.assertEqual(dataset.metadata["import_review_status"], "complete")
        steps = dataset.runs[0].steps
        self.assertEqual(steps[1].depends_on, ["call_001"])
        self.assertEqual(steps[2].depends_on, ["call_002"])
        self.assertEqual(steps[2].side_effects[0].kind.value, "write")
        self.assertEqual(steps[2].metadata["alignment_key"], "apply_address_change")
        self.assertEqual(
            steps[1].metadata["tool_output_representation"],
            "tau_tool_message_content_string",
        )

    def test_incomplete_review_is_rejected(self) -> None:
        review = load_tau_review(REVIEW)
        incomplete = review.model_copy(deep=True)
        del incomplete.simulations["sim-address-1"].calls["source-call-a3"]
        with self.assertRaisesRegex(TauImportError, "missing calls: source-call-a3"):
            import_tau_results(
                load_tau_results(RESULTS),
                dataset_id="tau_incomplete",
                simulation_ids=["sim-address-1"],
                review=incomplete,
            )

    def test_group_split_keeps_trials_together_and_blocks_trial_leakage(self) -> None:
        dataset = import_tau_results(
            load_tau_results(RESULTS),
            dataset_id="tau_groups",
            review=load_tau_review(REVIEW),
        )
        split = split_by_test_group_ids(dataset, ["address-change-holdout"])
        self.assertEqual(len(split.compile.runs), 2)
        self.assertEqual(len(split.test.runs), 1)
        self.assertEqual(
            {run.provenance.task_group_id for run in split.compile.runs},
            {"address-change"},
        )

        compile_data = dataset.model_copy(
            update={"runs": [dataset.runs[0]]}, deep=True
        )
        test_data = dataset.model_copy(
            update={"runs": [dataset.runs[1]]}, deep=True
        )
        with self.assertRaisesRegex(DatasetLeakageError, "source task groups"):
            assert_disjoint(compile_data, test_data)

    def test_non_retail_domain_is_rejected(self) -> None:
        source = dict(load_tau_results(RESULTS))
        source["info"] = dict(source["info"])
        source["info"]["environment_info"] = {"domain_name": "airline"}
        with self.assertRaisesRegex(TauImportError, "only the audited tau retail"):
            import_tau_results(source, dataset_id="wrong_domain")


if __name__ == "__main__":
    unittest.main()

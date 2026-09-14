"""Tests for conservative occurrence alignment and evidence-bearing DAG mining."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace2flow.asp import to_asp
from trace2flow.candidate import (
    AlignmentStatus,
    build_candidate_dag,
    mine_candidate_dag,
)
from trace2flow.io import load_trace_dataset
from trace2flow.models import DatasetPartition, TraceDataset
from trace2flow.upstream import (
    UPSTREAM_BASELINE_COMMIT,
    RuleProfile,
    UpstreamSignals,
    compile_with_upstream,
)

FIXTURE = ROOT / "tests" / "fixtures" / "typed_customer_support.json"


def make_dataset(
    runs: list[tuple[str, list[dict[str, object]]]],
    *,
    dataset_id: str = "synthetic_candidate_test",
) -> TraceDataset:
    return TraceDataset.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "partition": "compile",
            "metadata": {"synthetic": True},
            "runs": [
                {
                    "id": run_id,
                    "provenance": {
                        "kind": "synthetic",
                        "source": "candidate-test",
                        "source_run_id": run_id,
                    },
                    "steps": steps,
                    "status": "completed",
                }
                for run_id, steps in runs
            ],
        }
    )


def step(
    step_id: str,
    tool: str,
    *,
    depends_on: list[str] | None = None,
    alignment_key: str | None = None,
) -> dict[str, object]:
    metadata = {} if alignment_key is None else {"alignment_key": alignment_key}
    return {
        "id": step_id,
        "tool": tool,
        "params": {"value": 1, "enabled": False, "optional": None},
        "depends_on": depends_on or [],
        "status": "completed",
        "side_effects": [{"kind": "none"}],
        "metadata": metadata,
    }


def signals_for(dataset: TraceDataset) -> UpstreamSignals:
    return UpstreamSignals(
        source_sha256=to_asp(dataset).source_sha256,
        rules_sha256="0" * 64,
        compiler_sha256="1" * 64,
        baseline_commit=UPSTREAM_BASELINE_COMMIT,
        rule_profile=RuleProfile.STRICT,
        source_runs=len(dataset.runs),
        compiled_call_count=0,
        core_tools=[],
        phases={},
        conditionals=[],
        fusion_candidates=[],
        mutually_exclusive=[],
        conflicting_order_choices=[],
        variable_params={},
    )


class CandidateDagTest(unittest.TestCase):
    def test_real_upstream_signals_and_ambiguous_occurrences_are_retained(self) -> None:
        dataset = load_trace_dataset(FIXTURE)
        candidate = mine_candidate_dag(dataset)

        self.assertEqual(candidate.upstream.source_runs, 3)
        self.assertEqual(candidate.upstream.baseline_commit, UPSTREAM_BASELINE_COMMIT)
        self.assertEqual(
            candidate.upstream.compiler_sha256,
            hashlib.sha256((ROOT / "src" / "compile.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            candidate.upstream.rules_sha256,
            hashlib.sha256(
                (ROOT / "rules" / "mine_patterns.lp").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            set(candidate.upstream.core_tools),
            {
                "classify_issue",
                "lookup_customer",
                "lookup_order",
                "recommend_action",
                "update_ticket",
            },
        )

        nodes_by_tool = {node.tool: node for node in candidate.nodes}
        order_node = nodes_by_tool["lookup_order"]
        self.assertEqual(order_node.alignment_status, AlignmentStatus.UNRESOLVED)
        self.assertEqual(len(order_node.occurrences), 6)
        self.assertEqual(
            order_node.occurrence_count_by_run,
            {"support_run_1": 2, "support_run_2": 2, "support_run_3": 2},
        )

        accepted_tool_edges = {
            (
                next(node.tool for node in candidate.nodes if node.id == edge.source_node_id),
                next(node.tool for node in candidate.nodes if node.id == edge.target_node_id),
            ): len(edge.supporting_evidence)
            for edge in candidate.edges
        }
        self.assertEqual(
            accepted_tool_edges,
            {("classify_issue", "recommend_action"): 3, ("recommend_action", "update_ticket"): 3},
        )
        self.assertEqual(
            [item.reason for item in candidate.unresolved_dependencies],
            ["endpoint_alignment_unresolved", "endpoint_alignment_unresolved"],
        )

    def test_declared_keys_separate_repeated_tool_occurrences_across_reordering(self) -> None:
        dataset = make_dataset(
            [
                (
                    "run_1",
                    [
                        step("primary_1", "lookup_order", alignment_key="primary"),
                        step("secondary_1", "lookup_order", alignment_key="secondary"),
                    ],
                ),
                (
                    "run_2",
                    [
                        step("secondary_2", "lookup_order", alignment_key="secondary"),
                        step("primary_2", "lookup_order", alignment_key="primary"),
                    ],
                ),
            ]
        )
        candidate = build_candidate_dag(dataset, signals_for(dataset))

        self.assertEqual(len(candidate.nodes), 2)
        self.assertEqual(candidate.edges, [])
        self.assertEqual(candidate.unresolved_dependencies, [])
        self.assertTrue(
            all(node.alignment_status is AlignmentStatus.ALIGNED for node in candidate.nodes)
        )
        self.assertEqual(
            {node.alignment_basis.declared_alignment_key for node in candidate.nodes},
            {"primary", "secondary"},
        )
        self.assertTrue(all(len(node.occurrences) == 2 for node in candidate.nodes))

    def test_equal_common_values_do_not_resolve_indistinguishable_repetitions(self) -> None:
        dataset = make_dataset(
            [
                (
                    "run_1",
                    [step("same_1", "probe"), step("same_2", "probe")],
                ),
                (
                    "run_2",
                    [step("same_4", "probe"), step("same_3", "probe")],
                ),
            ]
        )
        candidate = build_candidate_dag(dataset, signals_for(dataset))

        self.assertEqual(len(candidate.nodes), 1)
        node = candidate.nodes[0]
        self.assertEqual(node.alignment_status, AlignmentStatus.UNRESOLVED)
        self.assertEqual(len(node.occurrences), 4)
        self.assertIn("run_1", node.unresolved_reason or "")
        self.assertIn("run_2", node.unresolved_reason or "")

    def test_reordered_independent_calls_do_not_create_dependencies(self) -> None:
        dataset = make_dataset(
            [
                ("run_1", [step("a_1", "tool_a"), step("b_1", "tool_b")]),
                ("run_2", [step("b_2", "tool_b"), step("a_2", "tool_a")]),
            ]
        )
        candidate = build_candidate_dag(dataset, signals_for(dataset))

        self.assertEqual(len(candidate.nodes), 2)
        self.assertEqual(candidate.edges, [])
        self.assertEqual(candidate.unresolved_dependencies, [])

    def test_reciprocal_dependencies_remain_conflicting(self) -> None:
        dataset = make_dataset(
            [
                (
                    "run_1",
                    [step("a_1", "tool_a"), step("b_1", "tool_b", depends_on=["a_1"])],
                ),
                (
                    "run_2",
                    [step("b_2", "tool_b"), step("a_2", "tool_a", depends_on=["b_2"])],
                ),
            ]
        )
        candidate = build_candidate_dag(dataset, signals_for(dataset))

        self.assertEqual(candidate.edges, [])
        self.assertEqual(len(candidate.unresolved_dependencies), 1)
        conflict = candidate.unresolved_dependencies[0]
        self.assertEqual(conflict.reason, "reciprocal_explicit_dependencies")
        self.assertEqual(len(conflict.candidates), 2)
        self.assertTrue(
            all(
                len(direction.supporting_evidence) == 1
                and len(direction.conflicting_evidence) == 1
                for direction in conflict.candidates
            )
        )

    def test_cross_run_cycle_is_removed_from_accepted_dag(self) -> None:
        dataset = make_dataset(
            [
                (
                    "run_1",
                    [
                        step("a_1", "tool_a"),
                        step("b_1", "tool_b", depends_on=["a_1"]),
                        step("c_1", "tool_c", depends_on=["b_1"]),
                    ],
                ),
                (
                    "run_2",
                    [
                        step("c_2", "tool_c"),
                        step("a_2", "tool_a", depends_on=["c_2"]),
                        step("b_2", "tool_b"),
                    ],
                ),
            ]
        )
        candidate = build_candidate_dag(dataset, signals_for(dataset))

        self.assertEqual(candidate.edges, [])
        self.assertEqual(len(candidate.unresolved_dependencies), 1)
        cycle = candidate.unresolved_dependencies[0]
        self.assertEqual(cycle.reason, "cross_run_cycle")
        self.assertEqual(len(cycle.candidates), 3)
        self.assertEqual(
            sum(len(direction.supporting_evidence) for direction in cycle.candidates),
            3,
        )

    def test_rejects_upstream_signals_from_another_dataset(self) -> None:
        first = make_dataset([("run_1", [step("a_1", "tool_a")])])
        second = make_dataset(
            [("run_2", [step("a_2", "tool_a")])],
            dataset_id="other_dataset",
        )

        with self.assertRaisesRegex(ValueError, "different source dataset"):
            build_candidate_dag(second, signals_for(first))

    def test_upstream_adapter_rejects_test_partition(self) -> None:
        dataset = load_trace_dataset(FIXTURE).model_copy(
            update={"partition": DatasetPartition.TEST}
        )

        with self.assertRaisesRegex(ValueError, "partitioned as 'compile'"):
            compile_with_upstream(dataset)


if __name__ == "__main__":
    unittest.main()

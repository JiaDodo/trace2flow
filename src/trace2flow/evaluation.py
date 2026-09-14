"""Held-out structural evaluation without execution-equivalence claims."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Literal

from pydantic import Field

from .candidate import AlignmentStatus, CandidateDag, occurrence_signature
from .datasets import assert_disjoint
from .io import canonical_json
from .models import DatasetPartition, StrictModel, TraceDataset


class StructuralDependency(StrictModel):
    source_node_id: str
    target_node_id: str


class StructuralRunResult(StrictModel):
    run_id: str
    task_group_id: str | None
    total_occurrences: int
    matched_occurrences: int
    unmatched_occurrences: list[str] = Field(default_factory=list)
    ambiguous_occurrences: list[str] = Field(default_factory=list)
    observed_candidate_node_ids: list[str] = Field(default_factory=list)
    missing_candidate_node_ids: list[str] = Field(default_factory=list)
    supported_candidate_edge_ids: list[str] = Field(default_factory=list)
    missing_candidate_edge_ids: list[str] = Field(default_factory=list)
    unseen_dependencies: list[StructuralDependency] = Field(default_factory=list)
    structurally_covered: bool


class StructuralEvaluationReport(StrictModel):
    schema_version: Literal["structure-evaluation/1.0"] = "structure-evaluation/1.0"
    validation_scope: Literal["held_out_structure_only"] = "held_out_structure_only"
    compile_dataset_id: str
    test_dataset_id: str
    candidate_source_sha256: str
    compile_task_group_ids: list[str]
    test_task_group_ids: list[str]
    candidate_nodes: int
    candidate_edges: int
    test_runs: int
    covered_runs: int
    all_runs_structurally_covered: bool
    execution_equivalence_claimed: Literal[False] = False
    run_results: list[StructuralRunResult]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "structure coverage does not compare final outputs or mutable state",
            "recorded tool responses are not replayed as execution evidence",
        ]
    )


def _group_ids(dataset: TraceDataset) -> list[str]:
    return sorted(
        {
            run.provenance.task_group_id
            for run in dataset.runs
            if run.provenance.task_group_id is not None
        }
    )


def evaluate_structure(
    candidate: CandidateDag,
    compile_dataset: TraceDataset,
    test_dataset: TraceDataset,
) -> StructuralEvaluationReport:
    """Measure whether declared held-out structure is covered by a candidate DAG."""

    if compile_dataset.partition is not DatasetPartition.COMPILE:
        raise ValueError("structural evaluation requires a 'compile' dataset")
    if test_dataset.partition is not DatasetPartition.TEST:
        raise ValueError("structural evaluation requires a 'test' dataset")
    if compile_dataset.metadata.get("import_review_status") == "required":
        raise ValueError("compile traces require complete import review")
    if test_dataset.metadata.get("import_review_status") == "required":
        raise ValueError("test traces require complete import review")
    assert_disjoint(compile_dataset, test_dataset)

    compile_sha256 = hashlib.sha256(
        canonical_json(compile_dataset).encode("utf-8")
    ).hexdigest()
    if candidate.source_dataset_id != compile_dataset.dataset_id:
        raise ValueError("candidate was produced from a different compile dataset id")
    if candidate.source_sha256 != compile_sha256:
        raise ValueError("candidate was produced from different compile dataset content")

    nodes_by_signature = {node.signature_sha256: node for node in candidate.nodes}
    candidate_node_ids = {node.id for node in candidate.nodes}
    candidate_edges = {
        (edge.source_node_id, edge.target_node_id): edge for edge in candidate.edges
    }
    run_results: list[StructuralRunResult] = []

    for run in test_dataset.runs:
        signature_counts = Counter(
            occurrence_signature(run, step) for step in run.steps
        )
        occurrence_nodes: dict[str, str] = {}
        unmatched: list[str] = []
        ambiguous: list[str] = []
        for step in run.steps:
            qualified_id = f"{run.id}:{step.id}"
            signature = occurrence_signature(run, step)
            node = nodes_by_signature.get(signature)
            if node is None:
                unmatched.append(qualified_id)
                continue
            if (
                node.alignment_status is AlignmentStatus.UNRESOLVED
                or signature_counts[signature] > 1
            ):
                ambiguous.append(qualified_id)
                continue
            occurrence_nodes[step.id] = node.id

        observed_node_ids = set(occurrence_nodes.values())
        observed_dependencies: set[tuple[str, str]] = set()
        for step in run.steps:
            target_node_id = occurrence_nodes.get(step.id)
            if target_node_id is None:
                continue
            for dependency_id in step.depends_on:
                source_node_id = occurrence_nodes.get(dependency_id)
                if source_node_id is not None:
                    observed_dependencies.add((source_node_id, target_node_id))

        supported_edges = sorted(
            edge.id
            for pair, edge in candidate_edges.items()
            if pair in observed_dependencies
        )
        missing_edges = sorted(
            edge.id
            for pair, edge in candidate_edges.items()
            if pair not in observed_dependencies
        )
        unseen_dependencies = [
            StructuralDependency(source_node_id=source, target_node_id=target)
            for source, target in sorted(
                observed_dependencies - set(candidate_edges)
            )
        ]
        missing_nodes = sorted(candidate_node_ids - observed_node_ids)
        structurally_covered = not (
            unmatched
            or ambiguous
            or missing_nodes
            or missing_edges
            or unseen_dependencies
        )
        run_results.append(
            StructuralRunResult(
                run_id=run.id,
                task_group_id=run.provenance.task_group_id,
                total_occurrences=len(run.steps),
                matched_occurrences=len(occurrence_nodes),
                unmatched_occurrences=sorted(unmatched),
                ambiguous_occurrences=sorted(ambiguous),
                observed_candidate_node_ids=sorted(observed_node_ids),
                missing_candidate_node_ids=missing_nodes,
                supported_candidate_edge_ids=supported_edges,
                missing_candidate_edge_ids=missing_edges,
                unseen_dependencies=unseen_dependencies,
                structurally_covered=structurally_covered,
            )
        )

    covered_runs = sum(result.structurally_covered for result in run_results)
    return StructuralEvaluationReport(
        compile_dataset_id=compile_dataset.dataset_id,
        test_dataset_id=test_dataset.dataset_id,
        candidate_source_sha256=candidate.source_sha256,
        compile_task_group_ids=_group_ids(compile_dataset),
        test_task_group_ids=_group_ids(test_dataset),
        candidate_nodes=len(candidate.nodes),
        candidate_edges=len(candidate.edges),
        test_runs=len(run_results),
        covered_runs=covered_runs,
        all_runs_structurally_covered=covered_runs == len(run_results),
        run_results=run_results,
    )


def structural_report_json(report: StructuralEvaluationReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

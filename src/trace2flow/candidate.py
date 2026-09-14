"""Conservative occurrence alignment and evidence-bearing candidate DAGs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .io import canonical_json
from .models import (
    DatasetPartition,
    SideEffect,
    StrictModel,
    TraceDataset,
    TraceRun,
    TraceStep,
)
from .upstream import RuleProfile, UpstreamSignals, compile_with_upstream


class AlignmentStatus(str, Enum):
    ALIGNED = "aligned"
    UNRESOLVED = "unresolved"


class OccurrenceReference(StrictModel):
    run_id: str
    step_id: str
    qualified_id: str


class AlignmentBasis(StrictModel):
    tool: str
    declared_alignment_key: str | None = None
    parameter_keys: list[str] = Field(default_factory=list)
    side_effects: list[SideEffect] = Field(default_factory=list)


class CandidateNode(StrictModel):
    id: str
    tool: str
    alignment_status: AlignmentStatus = Field(strict=False)
    alignment_basis: AlignmentBasis
    signature_sha256: str
    occurrences: list[OccurrenceReference]
    occurrence_count_by_run: dict[str, int]
    unresolved_reason: str | None = None
    upstream_core_tool: bool
    upstream_phases: list[int]


class DependencyEvidence(StrictModel):
    run_id: str
    source_occurrence_id: str
    target_occurrence_id: str
    declaration: Literal["depends_on"] = "depends_on"


class DagEdge(StrictModel):
    id: str
    source_node_id: str
    target_node_id: str
    supporting_evidence: list[DependencyEvidence] = Field(min_length=1)
    conflicting_evidence: list[DependencyEvidence] = Field(default_factory=list)


class DependencyDirection(StrictModel):
    source_node_id: str
    target_node_id: str
    supporting_evidence: list[DependencyEvidence] = Field(min_length=1)
    conflicting_evidence: list[DependencyEvidence] = Field(default_factory=list)


class UnresolvedDependency(StrictModel):
    reason: Literal[
        "endpoint_alignment_unresolved",
        "reciprocal_explicit_dependencies",
        "cross_run_cycle",
        "dependency_inside_unresolved_family",
    ]
    candidates: list[DependencyDirection] = Field(min_length=1)


class CandidateDag(StrictModel):
    """M2 evidence artifact, intentionally distinct from the M3 Workflow IR."""

    schema_version: Literal["candidate-dag/1.0"] = "candidate-dag/1.0"
    source_dataset_id: str
    source_sha256: str
    upstream: UpstreamSignals
    nodes: list[CandidateNode]
    edges: list[DagEdge]
    unresolved_dependencies: list[UnresolvedDependency]

    @model_validator(mode="after")
    def validate_graph(self) -> CandidateDag:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("candidate node ids must be unique")
        known_nodes = set(node_ids)
        nodes_by_id = {node.id: node for node in self.nodes}

        seen_occurrences: set[str] = set()
        for node in self.nodes:
            current = {item.qualified_id for item in node.occurrences}
            if len(current) != len(node.occurrences):
                raise ValueError(f"node '{node.id}' repeats an occurrence")
            overlap = seen_occurrences & current
            if overlap:
                raise ValueError(
                    "occurrences assigned to multiple candidate nodes: "
                    + ", ".join(sorted(overlap))
                )
            seen_occurrences.update(current)
            repeated = any(count > 1 for count in node.occurrence_count_by_run.values())
            if repeated and node.alignment_status is not AlignmentStatus.UNRESOLVED:
                raise ValueError(
                    f"node '{node.id}' merges repeated occurrences without resolution"
                )
            if node.alignment_status is AlignmentStatus.UNRESOLVED:
                if node.unresolved_reason is None:
                    raise ValueError(
                        f"unresolved node '{node.id}' requires an unresolved reason"
                    )
            elif node.unresolved_reason is not None:
                raise ValueError(
                    f"aligned node '{node.id}' cannot have an unresolved reason"
                )

        def validate_evidence(
            source_node_id: str,
            target_node_id: str,
            evidence: list[DependencyEvidence],
        ) -> None:
            source_occurrences = {
                item.qualified_id: item
                for item in nodes_by_id[source_node_id].occurrences
            }
            target_occurrences = {
                item.qualified_id: item
                for item in nodes_by_id[target_node_id].occurrences
            }
            for item in evidence:
                if item.source_occurrence_id not in source_occurrences:
                    raise ValueError(
                        f"dependency evidence references source occurrence outside "
                        f"node '{source_node_id}'"
                    )
                if item.target_occurrence_id not in target_occurrences:
                    raise ValueError(
                        f"dependency evidence references target occurrence outside "
                        f"node '{target_node_id}'"
                    )
                if (
                    item.run_id
                    != source_occurrences[item.source_occurrence_id].run_id
                    or item.run_id
                    != target_occurrences[item.target_occurrence_id].run_id
                ):
                    raise ValueError("dependency evidence must stay within one run")

        adjacency: dict[str, set[str]] = {node_id: set() for node_id in known_nodes}
        edge_ids: set[str] = set()
        edge_pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError(f"edge '{edge.id}' references an unknown node")
            if edge.source_node_id == edge.target_node_id:
                raise ValueError(f"edge '{edge.id}' is a self-cycle")
            if (
                nodes_by_id[edge.source_node_id].alignment_status
                is AlignmentStatus.UNRESOLVED
                or nodes_by_id[edge.target_node_id].alignment_status
                is AlignmentStatus.UNRESOLVED
            ):
                raise ValueError(f"edge '{edge.id}' has an unresolved endpoint")
            if edge.id in edge_ids:
                raise ValueError(f"duplicate edge id '{edge.id}'")
            pair = (edge.source_node_id, edge.target_node_id)
            if pair in edge_pairs:
                raise ValueError(f"duplicate edge {pair!r}")
            edge_ids.add(edge.id)
            edge_pairs.add(pair)
            validate_evidence(
                edge.source_node_id,
                edge.target_node_id,
                edge.supporting_evidence,
            )
            validate_evidence(
                edge.target_node_id,
                edge.source_node_id,
                edge.conflicting_evidence,
            )
            adjacency[edge.source_node_id].add(edge.target_node_id)

        for unresolved in self.unresolved_dependencies:
            for candidate in unresolved.candidates:
                if (
                    candidate.source_node_id not in known_nodes
                    or candidate.target_node_id not in known_nodes
                ):
                    raise ValueError("unresolved dependency references an unknown node")
                validate_evidence(
                    candidate.source_node_id,
                    candidate.target_node_id,
                    candidate.supporting_evidence,
                )
                validate_evidence(
                    candidate.target_node_id,
                    candidate.source_node_id,
                    candidate.conflicting_evidence,
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("accepted candidate edges must form a DAG")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target_id in sorted(adjacency[node_id]):
                visit(target_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(known_nodes):
            visit(node_id)
        return self


def candidate_json(candidate: CandidateDag) -> str:
    return (
        json.dumps(
            candidate.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _alignment_basis(run: TraceRun, step: TraceStep) -> AlignmentBasis:
    declared_key = step.metadata.get("alignment_key")
    if declared_key is not None:
        if not isinstance(declared_key, str) or not declared_key.strip():
            raise ValueError(
                f"{run.id}:{step.id} metadata.alignment_key must be a non-empty string"
            )
        return AlignmentBasis(tool=step.tool, declared_alignment_key=declared_key)

    side_effects = sorted(
        (effect.model_copy(deep=True) for effect in step.side_effects),
        key=lambda effect: (
            effect.kind.value,
            effect.target or "",
            str(effect.reversible),
        ),
    )
    return AlignmentBasis(
        tool=step.tool,
        parameter_keys=sorted(step.params),
        side_effects=side_effects,
    )


def _signature(basis: AlignmentBasis) -> str:
    payload = json.dumps(
        basis.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _edge_id(source_node_id: str, target_node_id: str) -> str:
    digest = hashlib.sha256(
        f"{source_node_id}\0{target_node_id}".encode()
    ).hexdigest()
    return f"edge_{digest[:12]}"


def _evidence_key(item: DependencyEvidence) -> tuple[str, str, str]:
    return (item.run_id, item.source_occurrence_id, item.target_occurrence_id)


def _can_reach(
    adjacency: dict[str, set[str]], source_node_id: str, target_node_id: str
) -> bool:
    pending = [source_node_id]
    seen: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id == target_node_id:
            return True
        if node_id in seen:
            continue
        seen.add(node_id)
        pending.extend(sorted(adjacency.get(node_id, ()), reverse=True))
    return False


def build_candidate_dag(
    dataset: TraceDataset,
    upstream: UpstreamSignals,
) -> CandidateDag:
    """Align occurrences conservatively and aggregate only explicit dependencies."""

    if dataset.partition is not DatasetPartition.COMPILE:
        raise ValueError("candidate mining requires a dataset partitioned as 'compile'")
    source_sha256 = hashlib.sha256(canonical_json(dataset).encode("utf-8")).hexdigest()
    if upstream.source_sha256 != source_sha256:
        raise ValueError("upstream signals were produced from a different source dataset")

    grouped: dict[str, list[tuple[TraceRun, TraceStep, AlignmentBasis]]] = defaultdict(list)
    for run in dataset.runs:
        for step in run.steps:
            basis = _alignment_basis(run, step)
            grouped[_signature(basis)].append((run, step, basis))

    phase_by_tool: dict[str, list[int]] = defaultdict(list)
    for phase, tools in upstream.phases.items():
        for tool in tools:
            phase_by_tool[tool].append(phase)

    nodes: list[CandidateNode] = []
    occurrence_to_node: dict[tuple[str, str], str] = {}
    status_by_node: dict[str, AlignmentStatus] = {}
    for signature in sorted(grouped):
        members = grouped[signature]
        basis = members[0][2]
        counts = Counter(run.id for run, _, _ in members)
        repeated_runs = sorted(run_id for run_id, count in counts.items() if count > 1)
        status = (
            AlignmentStatus.UNRESOLVED if repeated_runs else AlignmentStatus.ALIGNED
        )
        node_id = f"node_{signature[:12]}"
        occurrences = sorted(
            (
                OccurrenceReference(
                    run_id=run.id,
                    step_id=step.id,
                    qualified_id=f"{run.id}:{step.id}",
                )
                for run, step, _ in members
            ),
            key=lambda item: (item.run_id, item.step_id),
        )
        nodes.append(
            CandidateNode(
                id=node_id,
                tool=basis.tool,
                alignment_status=status,
                alignment_basis=basis,
                signature_sha256=signature,
                occurrences=occurrences,
                occurrence_count_by_run=dict(sorted(counts.items())),
                unresolved_reason=(
                    "multiple indistinguishable occurrences in run(s): "
                    + ", ".join(repeated_runs)
                    if repeated_runs
                    else None
                ),
                upstream_core_tool=basis.tool in upstream.core_tools,
                upstream_phases=sorted(phase_by_tool.get(basis.tool, [])),
            )
        )
        status_by_node[node_id] = status
        for run, step, _ in members:
            occurrence_to_node[(run.id, step.id)] = node_id

    raw_edges: dict[tuple[str, str], list[DependencyEvidence]] = defaultdict(list)
    for run in dataset.runs:
        for target_step in run.steps:
            target_node = occurrence_to_node[(run.id, target_step.id)]
            for source_step_id in target_step.depends_on:
                source_node = occurrence_to_node[(run.id, source_step_id)]
                raw_edges[(source_node, target_node)].append(
                    DependencyEvidence(
                        run_id=run.id,
                        source_occurrence_id=f"{run.id}:{source_step_id}",
                        target_occurrence_id=f"{run.id}:{target_step.id}",
                    )
                )
    raw_edges = {
        key: sorted(evidence, key=_evidence_key) for key, evidence in raw_edges.items()
    }

    unresolved: list[UnresolvedDependency] = []
    eligible: dict[tuple[str, str], list[DependencyEvidence]] = {}
    processed: set[tuple[str, str]] = set()
    for key in sorted(raw_edges):
        if key in processed:
            continue
        source_node, target_node = key
        evidence = raw_edges[key]
        if source_node == target_node:
            unresolved.append(
                UnresolvedDependency(
                    reason="dependency_inside_unresolved_family",
                    candidates=[
                        DependencyDirection(
                            source_node_id=source_node,
                            target_node_id=target_node,
                            supporting_evidence=evidence,
                        )
                    ],
                )
            )
            processed.add(key)
            continue

        reverse = (target_node, source_node)
        if reverse in raw_edges:
            reverse_evidence = raw_edges[reverse]
            unresolved.append(
                UnresolvedDependency(
                    reason="reciprocal_explicit_dependencies",
                    candidates=[
                        DependencyDirection(
                            source_node_id=source_node,
                            target_node_id=target_node,
                            supporting_evidence=evidence,
                            conflicting_evidence=reverse_evidence,
                        ),
                        DependencyDirection(
                            source_node_id=target_node,
                            target_node_id=source_node,
                            supporting_evidence=reverse_evidence,
                            conflicting_evidence=evidence,
                        ),
                    ],
                )
            )
            processed.update((key, reverse))
            continue

        if (
            status_by_node[source_node] is AlignmentStatus.UNRESOLVED
            or status_by_node[target_node] is AlignmentStatus.UNRESOLVED
        ):
            unresolved.append(
                UnresolvedDependency(
                    reason="endpoint_alignment_unresolved",
                    candidates=[
                        DependencyDirection(
                            source_node_id=source_node,
                            target_node_id=target_node,
                            supporting_evidence=evidence,
                        )
                    ],
                )
            )
            processed.add(key)
            continue

        eligible[key] = evidence
        processed.add(key)

    adjacency: dict[str, set[str]] = defaultdict(set)
    for source_node, target_node in eligible:
        adjacency[source_node].add(target_node)
    cyclic_keys = {
        (source_node, target_node)
        for source_node, target_node in eligible
        if _can_reach(adjacency, target_node, source_node)
    }
    if cyclic_keys:
        undirected: dict[str, set[str]] = defaultdict(set)
        for source_node, target_node in cyclic_keys:
            undirected[source_node].add(target_node)
            undirected[target_node].add(source_node)
        remaining_nodes = set(undirected)
        while remaining_nodes:
            pending = [min(remaining_nodes)]
            component: set[str] = set()
            while pending:
                node_id = pending.pop()
                if node_id in component:
                    continue
                component.add(node_id)
                pending.extend(sorted(undirected[node_id] - component, reverse=True))
            remaining_nodes -= component
            component_edges = sorted(
                key
                for key in cyclic_keys
                if key[0] in component and key[1] in component
            )
            unresolved.append(
                UnresolvedDependency(
                    reason="cross_run_cycle",
                    candidates=[
                        DependencyDirection(
                            source_node_id=key[0],
                            target_node_id=key[1],
                            supporting_evidence=eligible[key],
                        )
                        for key in component_edges
                    ],
                )
            )

    edges = [
        DagEdge(
            id=_edge_id(source_node, target_node),
            source_node_id=source_node,
            target_node_id=target_node,
            supporting_evidence=evidence,
        )
        for (source_node, target_node), evidence in sorted(eligible.items())
        if (source_node, target_node) not in cyclic_keys
    ]

    return CandidateDag(
        source_dataset_id=dataset.dataset_id,
        source_sha256=source_sha256,
        upstream=upstream,
        nodes=sorted(nodes, key=lambda node: node.id),
        edges=sorted(edges, key=lambda edge: edge.id),
        unresolved_dependencies=sorted(
            unresolved,
            key=lambda item: (
                item.reason,
                item.candidates[0].source_node_id,
                item.candidates[0].target_node_id,
            ),
        ),
    )


def mine_candidate_dag(
    dataset: TraceDataset,
    rule_profile: RuleProfile = RuleProfile.STRICT,
) -> CandidateDag:
    upstream = compile_with_upstream(dataset, rule_profile)
    return build_candidate_dag(dataset, upstream.signals)

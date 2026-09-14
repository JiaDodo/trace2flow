"""Framework-independent Workflow IR and conservative binding resolution."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from .candidate import (
    AlignmentStatus,
    CandidateDag,
    DependencyEvidence,
    OccurrenceReference,
)
from .io import canonical_json
from .models import SideEffect, StrictModel, TraceDataset, TraceRun, TraceStep

JsonPath = list[str | int]


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class BindingEvidence(StrictModel):
    run_id: str
    target_occurrence_id: str
    source_kind: Literal["constant", "task_input", "tool_output"]
    source_path: JsonPath = Field(default_factory=list)
    source_occurrence_id: str | None = None
    observed_value: JsonValue


class BindingCandidate(StrictModel):
    kind: Literal["constant", "task_input", "tool_output"]
    path: JsonPath = Field(default_factory=list)
    source_node_id: str | None = None
    value: JsonValue = None
    rationale: str
    evidence: list[BindingEvidence] = Field(min_length=1)


class ConstantBinding(StrictModel):
    kind: Literal["constant"] = "constant"
    value: JsonValue
    declared: Literal[True] = True
    rationale: Literal["explicit_declaration"] = "explicit_declaration"
    evidence: list[BindingEvidence] = Field(min_length=1)


class TaskInputBinding(StrictModel):
    kind: Literal["task_input"] = "task_input"
    path: JsonPath = Field(min_length=1)
    declared: Literal[True] = True
    rationale: Literal["explicit_declaration"] = "explicit_declaration"
    evidence: list[BindingEvidence] = Field(min_length=1)


class ToolOutputBinding(StrictModel):
    kind: Literal["tool_output"] = "tool_output"
    source_node_id: str
    path: JsonPath = Field(default_factory=list)
    declared: Literal[True] = True
    rationale: Literal["explicit_declaration"] = "explicit_declaration"
    evidence: list[BindingEvidence] = Field(min_length=1)


class UnresolvedBinding(StrictModel):
    kind: Literal["unresolved"] = "unresolved"
    reason: str
    observed_values: list[JsonValue]
    candidates: list[BindingCandidate] = Field(default_factory=list)


ParameterBinding = Annotated[
    ConstantBinding | TaskInputBinding | ToolOutputBinding | UnresolvedBinding,
    Field(discriminator="kind"),
]


class ConstantBindingSpec(StrictModel):
    kind: Literal["constant"] = "constant"
    value: JsonValue


class TaskInputBindingSpec(StrictModel):
    kind: Literal["task_input"] = "task_input"
    path: JsonPath = Field(min_length=1)


class ToolOutputBindingSpec(StrictModel):
    kind: Literal["tool_output"] = "tool_output"
    source_node_id: str
    path: JsonPath = Field(default_factory=list)


BindingSpec = Annotated[
    ConstantBindingSpec | TaskInputBindingSpec | ToolOutputBindingSpec,
    Field(discriminator="kind"),
]


class BindingOverride(StrictModel):
    node_id: str
    parameter: str
    binding: BindingSpec


class ResolutionPlan(StrictModel):
    """Human/config declarations required to promote candidates to bindings."""

    binding_overrides: list[BindingOverride] = Field(default_factory=list)
    confirmed_branch_nodes: list[str] = Field(default_factory=list)
    confirmed_side_effect_nodes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> ResolutionPlan:
        keys = [(item.node_id, item.parameter) for item in self.binding_overrides]
        if len(keys) != len(set(keys)):
            raise ValueError("binding overrides must be unique by node and parameter")
        for field_name in ("confirmed_branch_nodes", "confirmed_side_effect_nodes"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        return self


class WorkflowEdge(StrictModel):
    id: str
    source_node_id: str
    target_node_id: str
    evidence: list[DependencyEvidence] = Field(min_length=1)
    rationale: Literal["explicit_depends_on"] = "explicit_depends_on"


class WorkflowNode(StrictModel):
    id: str
    tool: str
    occurrences: list[OccurrenceReference]
    parameters: dict[str, ParameterBinding]
    side_effects: list[SideEffect]
    alignment_status: AlignmentStatus = Field(strict=False)
    branch_resolution: ResolutionStatus = Field(strict=False)
    branch_reason: str | None = None
    side_effect_resolution: ResolutionStatus = Field(strict=False)
    side_effect_reason: str | None = None

    @model_validator(mode="after")
    def validate_resolution_reasons(self) -> WorkflowNode:
        pairs = (
            (self.branch_resolution, self.branch_reason, "branch"),
            (self.side_effect_resolution, self.side_effect_reason, "side effect"),
        )
        for status, reason, label in pairs:
            if status is ResolutionStatus.UNRESOLVED and reason is None:
                raise ValueError(f"unresolved {label} requires a reason")
            if status is ResolutionStatus.RESOLVED and reason is not None:
                raise ValueError(f"resolved {label} cannot retain a reason")
        return self


class WorkflowIR(StrictModel):
    schema_version: Literal["workflow-ir/1.0"] = "workflow-ir/1.0"
    workflow_id: str
    source_dataset_id: str
    source_sha256: str
    candidate_schema_version: Literal["candidate-dag/1.0"] = "candidate-dag/1.0"
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    unresolved_dependencies: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_workflow(self) -> WorkflowIR:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow node ids must be unique")
        known_nodes = set(node_ids)
        adjacency = {node_id: set() for node_id in known_nodes}
        edge_pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            pair = (edge.source_node_id, edge.target_node_id)
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError(f"workflow edge '{edge.id}' references an unknown node")
            if pair in edge_pairs:
                raise ValueError(f"duplicate workflow edge {pair!r}")
            edge_pairs.add(pair)
            adjacency[edge.source_node_id].add(edge.target_node_id)

        for node in self.nodes:
            for parameter, binding in node.parameters.items():
                if isinstance(binding, ToolOutputBinding):
                    if binding.source_node_id not in known_nodes:
                        raise ValueError(
                            f"binding '{node.id}.{parameter}' references an unknown node"
                        )
                    if (binding.source_node_id, node.id) not in edge_pairs:
                        raise ValueError(
                            f"binding '{node.id}.{parameter}' lacks a dependency edge"
                        )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("workflow edges must form a DAG")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target in sorted(adjacency[node_id]):
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(known_nodes):
            visit(node_id)
        return self

    def execution_blockers(self) -> list[str]:
        blockers: list[str] = []
        if self.unresolved_dependencies:
            blockers.append(
                f"{self.unresolved_dependencies} unresolved dependency group(s)"
            )
        for node in self.nodes:
            if node.alignment_status is AlignmentStatus.UNRESOLVED:
                blockers.append(f"node {node.id} has unresolved occurrence alignment")
            for parameter, binding in node.parameters.items():
                if isinstance(binding, UnresolvedBinding):
                    blockers.append(f"parameter {node.id}.{parameter} is unresolved")
            if node.branch_resolution is ResolutionStatus.UNRESOLVED:
                blockers.append(f"node {node.id} has unresolved branch semantics")
            if node.side_effect_resolution is ResolutionStatus.UNRESOLVED:
                blockers.append(f"node {node.id} has unresolved side effects")
        return blockers


_WORKFLOW_ADAPTER = TypeAdapter(WorkflowIR)


def workflow_ir_json(workflow: WorkflowIR) -> str:
    return (
        json.dumps(
            workflow.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def loads_workflow_ir(text: str) -> WorkflowIR:
    return _WORKFLOW_ADAPTER.validate_json(text, strict=True)


def _json_token(value: JsonValue) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _walk_json(value: JsonValue, path: JsonPath | None = None):
    current_path = [] if path is None else path
    yield current_path, value
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _walk_json(value[key], [*current_path, key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json(item, [*current_path, index])


def _get_path(value: JsonValue, path: JsonPath) -> JsonValue:
    current = value
    for part in path:
        valid_object_key = (
            isinstance(part, str) and isinstance(current, dict) and part in current
        )
        valid_list_index = (
            isinstance(part, int)
            and not isinstance(part, bool)
            and isinstance(current, list)
            and 0 <= part < len(current)
        )
        if valid_object_key or valid_list_index:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _trace_indexes(dataset: TraceDataset):
    runs = {run.id: run for run in dataset.runs}
    steps = {
        (run.id, step.id): step for run in dataset.runs for step in run.steps
    }
    return runs, steps


def _step_for_qualified_id(
    run_id: str,
    qualified_id: str,
    steps: dict[tuple[str, str], TraceStep],
) -> TraceStep | None:
    return next(
        (
            step
            for (candidate_run_id, step_id), step in steps.items()
            if candidate_run_id == run_id
            and f"{candidate_run_id}:{step_id}" == qualified_id
        ),
        None,
    )


def _observed_parameter_values(
    occurrences: list[OccurrenceReference],
    parameter: str,
    steps: dict[tuple[str, str], TraceStep],
) -> tuple[list[tuple[OccurrenceReference, JsonValue]], list[str]]:
    values: list[tuple[OccurrenceReference, JsonValue]] = []
    missing: list[str] = []
    for occurrence in occurrences:
        step = steps[(occurrence.run_id, occurrence.step_id)]
        if parameter not in step.params:
            missing.append(occurrence.qualified_id)
        else:
            values.append((occurrence, step.params[parameter]))
    return values, missing


def _constant_candidate(
    values: list[tuple[OccurrenceReference, JsonValue]],
) -> BindingCandidate | None:
    tokens = {_json_token(value) for _, value in values}
    if len(tokens) != 1 or not values:
        return None
    value = values[0][1]
    return BindingCandidate(
        kind="constant",
        value=value,
        rationale="observed invariant; requires an explicit business declaration",
        evidence=[
            BindingEvidence(
                run_id=occurrence.run_id,
                target_occurrence_id=occurrence.qualified_id,
                source_kind="constant",
                observed_value=value,
            )
            for occurrence, value in values
        ],
    )


def _task_input_candidates(
    values: list[tuple[OccurrenceReference, JsonValue]],
    runs: dict[str, TraceRun],
) -> list[BindingCandidate]:
    common_paths: set[tuple[str | int, ...]] | None = None
    matches_by_occurrence: dict[str, dict[tuple[str | int, ...], JsonValue]] = {}
    for occurrence, observed in values:
        matches = {
            tuple(path): value
            for path, value in _walk_json(runs[occurrence.run_id].inputs)
            if path and _json_token(value) == _json_token(observed)
        }
        matches_by_occurrence[occurrence.qualified_id] = matches
        common_paths = set(matches) if common_paths is None else common_paths & set(matches)
    return [
        BindingCandidate(
            kind="task_input",
            path=list(path),
            rationale="value equality across runs; declaration required because equality is not lineage",
            evidence=[
                BindingEvidence(
                    run_id=occurrence.run_id,
                    target_occurrence_id=occurrence.qualified_id,
                    source_kind="task_input",
                    source_path=list(path),
                    observed_value=matches_by_occurrence[occurrence.qualified_id][path],
                )
                for occurrence, _ in values
            ],
        )
        for path in sorted(common_paths or (), key=lambda item: repr(item))
    ]


def _tool_output_candidates(
    values: list[tuple[OccurrenceReference, JsonValue]],
    incoming_edges: list[WorkflowEdge],
    steps: dict[tuple[str, str], TraceStep],
) -> list[BindingCandidate]:
    candidates: list[BindingCandidate] = []
    for edge in incoming_edges:
        evidence_by_target: dict[str, list[DependencyEvidence]] = defaultdict(list)
        for evidence in edge.evidence:
            evidence_by_target[evidence.target_occurrence_id].append(evidence)
        common_paths: set[tuple[str | int, ...]] | None = None
        matches_by_target: dict[str, dict[tuple[str | int, ...], tuple[JsonValue, str]]] = {}
        valid = True
        for occurrence, observed in values:
            links = evidence_by_target.get(occurrence.qualified_id, [])
            if len(links) != 1:
                valid = False
                break
            link = links[0]
            source_step = _step_for_qualified_id(
                link.run_id,
                link.source_occurrence_id,
                steps,
            )
            if source_step is None:
                valid = False
                break
            matches = {
                tuple(path): (value, link.source_occurrence_id)
                for path, value in _walk_json(source_step.output)
                if _json_token(value) == _json_token(observed)
            }
            matches_by_target[occurrence.qualified_id] = matches
            common_paths = set(matches) if common_paths is None else common_paths & set(matches)
        if not valid:
            continue
        for path in sorted(common_paths or (), key=lambda item: repr(item)):
            candidates.append(
                BindingCandidate(
                    kind="tool_output",
                    path=list(path),
                    source_node_id=edge.source_node_id,
                    rationale=(
                        "value equality along an explicit dependency; declaration required "
                        "because equality alone is not field lineage"
                    ),
                    evidence=[
                        BindingEvidence(
                            run_id=occurrence.run_id,
                            target_occurrence_id=occurrence.qualified_id,
                            source_kind="tool_output",
                            source_path=list(path),
                            source_occurrence_id=matches_by_target[
                                occurrence.qualified_id
                            ][path][1],
                            observed_value=matches_by_target[
                                occurrence.qualified_id
                            ][path][0],
                        )
                        for occurrence, _ in values
                    ],
                )
            )
    return candidates


def _resolve_declared_binding(
    node_id: str,
    parameter: str,
    spec: BindingSpec,
    values: list[tuple[OccurrenceReference, JsonValue]],
    runs: dict[str, TraceRun],
    steps: dict[tuple[str, str], TraceStep],
    incoming_edges: list[WorkflowEdge],
) -> ParameterBinding:
    if isinstance(spec, ConstantBindingSpec):
        if any(_json_token(value) != _json_token(spec.value) for _, value in values):
            raise ValueError(
                f"declared constant for '{node_id}.{parameter}' contradicts observations"
            )
        return ConstantBinding(
            value=spec.value,
            evidence=[
                BindingEvidence(
                    run_id=occurrence.run_id,
                    target_occurrence_id=occurrence.qualified_id,
                    source_kind="constant",
                    observed_value=value,
                )
                for occurrence, value in values
            ],
        )

    if isinstance(spec, TaskInputBindingSpec):
        evidence: list[BindingEvidence] = []
        for occurrence, observed in values:
            try:
                source_value = _get_path(runs[occurrence.run_id].inputs, spec.path)
            except KeyError:
                raise ValueError(
                    f"declared task input for '{node_id}.{parameter}' is missing in "
                    f"run '{occurrence.run_id}'"
                ) from None
            if _json_token(source_value) != _json_token(observed):
                raise ValueError(
                    f"declared task input for '{node_id}.{parameter}' contradicts "
                    f"run '{occurrence.run_id}'"
                )
            evidence.append(
                BindingEvidence(
                    run_id=occurrence.run_id,
                    target_occurrence_id=occurrence.qualified_id,
                    source_kind="task_input",
                    source_path=spec.path,
                    observed_value=source_value,
                )
            )
        return TaskInputBinding(path=spec.path, evidence=evidence)

    edge = next(
        (
            item
            for item in incoming_edges
            if item.source_node_id == spec.source_node_id
        ),
        None,
    )
    if edge is None:
        raise ValueError(
            f"declared output binding for '{node_id}.{parameter}' lacks an accepted edge"
        )
    evidence_by_target: dict[str, list[DependencyEvidence]] = defaultdict(list)
    for item in edge.evidence:
        evidence_by_target[item.target_occurrence_id].append(item)
    binding_evidence: list[BindingEvidence] = []
    for occurrence, observed in values:
        links = evidence_by_target.get(occurrence.qualified_id, [])
        if len(links) != 1:
            raise ValueError(
                f"declared output binding for '{node_id}.{parameter}' has ambiguous "
                f"source occurrence in '{occurrence.run_id}'"
            )
        link = links[0]
        source_step = _step_for_qualified_id(
            link.run_id,
            link.source_occurrence_id,
            steps,
        )
        try:
            source_value = _get_path(source_step.output, spec.path) if source_step else None
        except KeyError:
            raise ValueError(
                f"declared output path for '{node_id}.{parameter}' is missing in "
                f"run '{occurrence.run_id}'"
            ) from None
        if source_step is None or _json_token(source_value) != _json_token(observed):
            raise ValueError(
                f"declared output binding for '{node_id}.{parameter}' contradicts "
                f"run '{occurrence.run_id}'"
            )
        binding_evidence.append(
            BindingEvidence(
                run_id=occurrence.run_id,
                target_occurrence_id=occurrence.qualified_id,
                source_kind="tool_output",
                source_path=spec.path,
                source_occurrence_id=link.source_occurrence_id,
                observed_value=source_value,
            )
        )
    return ToolOutputBinding(
        source_node_id=spec.source_node_id,
        path=spec.path,
        evidence=binding_evidence,
    )


def build_workflow_ir(
    dataset: TraceDataset,
    candidate: CandidateDag,
    resolution: ResolutionPlan | None = None,
) -> WorkflowIR:
    """Build an IR without promoting equality or invariance to confirmed lineage."""

    source_sha256 = hashlib.sha256(canonical_json(dataset).encode("utf-8")).hexdigest()
    if candidate.source_sha256 != source_sha256:
        raise ValueError("candidate DAG was produced from a different source dataset")
    plan = resolution or ResolutionPlan()
    candidate_node_ids = {node.id for node in candidate.nodes}
    referenced_node_ids = {
        override.node_id for override in plan.binding_overrides
    } | set(plan.confirmed_branch_nodes) | set(plan.confirmed_side_effect_nodes)
    unknown = sorted(referenced_node_ids - candidate_node_ids)
    if unknown:
        raise ValueError("resolution plan references unknown node(s): " + ", ".join(unknown))

    overrides = {
        (item.node_id, item.parameter): item.binding
        for item in plan.binding_overrides
    }
    runs, steps = _trace_indexes(dataset)
    edges = [
        WorkflowEdge(
            id=edge.id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            evidence=edge.supporting_evidence,
        )
        for edge in candidate.edges
    ]
    incoming: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target_node_id].append(edge)

    workflow_nodes: list[WorkflowNode] = []
    consumed_overrides: set[tuple[str, str]] = set()
    conditional_tools = {item.tool for item in candidate.upstream.conditionals}
    conditional_tools.update(
        tool for pair in candidate.upstream.mutually_exclusive for tool in pair
    )
    for candidate_node in candidate.nodes:
        parameter_names = sorted(
            {
                parameter
                for occurrence in candidate_node.occurrences
                for parameter in steps[(occurrence.run_id, occurrence.step_id)].params
            }
        )
        parameters: dict[str, ParameterBinding] = {}
        for parameter in parameter_names:
            values, missing = _observed_parameter_values(
                candidate_node.occurrences,
                parameter,
                steps,
            )
            override = overrides.get((candidate_node.id, parameter))
            if override is not None:
                if missing:
                    raise ValueError(
                        f"cannot resolve '{candidate_node.id}.{parameter}'; missing in "
                        + ", ".join(missing)
                    )
                parameters[parameter] = _resolve_declared_binding(
                    candidate_node.id,
                    parameter,
                    override,
                    values,
                    runs,
                    steps,
                    incoming[candidate_node.id],
                )
                consumed_overrides.add((candidate_node.id, parameter))
                continue

            candidates: list[BindingCandidate] = []
            if not missing:
                constant = _constant_candidate(values)
                if constant is not None:
                    candidates.append(constant)
                candidates.extend(_task_input_candidates(values, runs))
                candidates.extend(
                    _tool_output_candidates(
                        values,
                        incoming[candidate_node.id],
                        steps,
                    )
                )
            observed_by_token = {_json_token(value): value for _, value in values}
            parameters[parameter] = UnresolvedBinding(
                reason=(
                    "parameter is absent from occurrence(s): " + ", ".join(missing)
                    if missing
                    else "candidate evidence requires an explicit binding declaration"
                ),
                observed_values=[
                    observed_by_token[token] for token in sorted(observed_by_token)
                ],
                candidates=candidates,
            )

        branch_unresolved = (
            candidate_node.tool in conditional_tools
            and candidate_node.id not in plan.confirmed_branch_nodes
        )
        has_write = any(
            effect.kind.value == "write"
            for occurrence in candidate_node.occurrences
            for effect in steps[(occurrence.run_id, occurrence.step_id)].side_effects
        )
        side_effect_unresolved = (
            has_write and candidate_node.id not in plan.confirmed_side_effect_nodes
        )
        side_effects_by_token = {
            _json_token(effect.model_dump(mode="json")): effect.model_copy(deep=True)
            for occurrence in candidate_node.occurrences
            for effect in steps[
                (occurrence.run_id, occurrence.step_id)
            ].side_effects
        }
        workflow_nodes.append(
            WorkflowNode(
                id=candidate_node.id,
                tool=candidate_node.tool,
                occurrences=candidate_node.occurrences,
                parameters=parameters,
                side_effects=[
                    side_effects_by_token[token]
                    for token in sorted(side_effects_by_token)
                ],
                alignment_status=candidate_node.alignment_status,
                branch_resolution=(
                    ResolutionStatus.UNRESOLVED
                    if branch_unresolved
                    else ResolutionStatus.RESOLVED
                ),
                branch_reason=(
                    "upstream reported conditional or mutually-exclusive behavior"
                    if branch_unresolved
                    else None
                ),
                side_effect_resolution=(
                    ResolutionStatus.UNRESOLVED
                    if side_effect_unresolved
                    else ResolutionStatus.RESOLVED
                ),
                side_effect_reason=(
                    "write side effect requires explicit confirmation"
                    if side_effect_unresolved
                    else None
                ),
            )
        )

    unused = sorted(set(overrides) - consumed_overrides)
    if unused:
        formatted = ", ".join(f"{node}.{parameter}" for node, parameter in unused)
        raise ValueError("resolution plan references unknown parameter(s): " + formatted)

    return WorkflowIR(
        workflow_id=f"{dataset.dataset_id}-workflow",
        source_dataset_id=dataset.dataset_id,
        source_sha256=source_sha256,
        nodes=sorted(workflow_nodes, key=lambda node: node.id),
        edges=sorted(edges, key=lambda edge: edge.id),
        unresolved_dependencies=len(candidate.unresolved_dependencies),
    )

"""Exhaustive, hash-bound declarations for Agent recordings; no inferred lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from .agent_collect import SCHEMAS
from .agent_corpus import (
    CorpusPlan,
    assert_record_case,
    digest,
    load_plan,
    make_collector,
)
from .candidate import AlignmentStatus, CandidateDag
from .io import canonical_json, load_trace_dataset, loads_json_document
from .ir import ResolutionPlan
from .models import SideEffect, StrictModel, TraceDataset
from .runtime import get_path


class BindingDeclaration(StrictModel):
    kind: Literal["constant", "task_input", "tool_output", "unresolved"]
    path: list[str | int] = Field(default_factory=list)
    source_call_id: str | None = None
    value: JsonValue = None
    rationale: str = Field(min_length=1)


class CallReview(StrictModel):
    depends_on: list[str]
    side_effects: list[SideEffect] = Field(min_length=1)
    alignment_key: str | None = None
    bindings: dict[str, BindingDeclaration]


class RecordingReview(StrictModel):
    schema_version: Literal["agent-recording-review/1.0"]
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1)
    redaction_confirmed: Literal[True]
    review_minutes: float = Field(ge=0)
    decision: Literal["include", "exclude_from_compilation"]
    rationale: str = Field(min_length=1)
    calls: dict[str, CallReview]


def registered_effects(tool: str) -> list[dict]:
    return {
        "lookup_customer": [
            {"kind": "read", "target": "mock.customers", "reversible": None}
        ],
        "lookup_order": [{"kind": "read", "target": "mock.orders", "reversible": None}],
        "update_ticket": [
            {"kind": "write", "target": "mock.tickets", "reversible": True}
        ],
    }.get(tool, [{"kind": "none", "target": None, "reversible": None}])


def draft_review(plan: CorpusPlan, raw_content: bytes) -> dict:
    """Create an intentionally unapproved template; never assert human review occurred."""
    record = loads_json_document(raw_content.decode("utf-8"))
    assert_record_case(plan, record)
    ids = [call["id"] for call in record["calls"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate dispatched occurrence")
    return {
        "schema_version": "agent-recording-review/1.0",
        "raw_sha256": hashlib.sha256(raw_content).hexdigest(),
        "plan_sha256": digest(plan.model_dump(mode="json")),
        "reviewer": "",
        "redaction_confirmed": False,
        "review_minutes": 0.0,
        "decision": "exclude_from_compilation",
        "rationale": "TODO: review original events, arguments, results and state",
        "calls": {
            call["id"]: {
                "depends_on": [],
                "side_effects": registered_effects(call["tool"]),
                "alignment_key": None,
                "bindings": {
                    parameter: {
                        "kind": "unresolved",
                        "rationale": "TODO: declare a justified source or retain ambiguity",
                    }
                    for parameter in call["params"]
                },
            }
            for call in record["calls"]
        },
    }


def review_recording(
    plan: CorpusPlan, raw_content: bytes, review: RecordingReview
) -> TraceDataset | None:
    if hashlib.sha256(raw_content).hexdigest() != review.raw_sha256:
        raise ValueError("raw recording SHA mismatch")
    if digest(plan.model_dump(mode="json")) != review.plan_sha256:
        raise ValueError("review plan SHA mismatch")
    record = loads_json_document(raw_content.decode("utf-8"))
    case = assert_record_case(plan, record)
    ids = [call["id"] for call in record["calls"]]
    if len(ids) != len(set(ids)) or set(ids) != set(review.calls):
        raise ValueError("review must cover every distinct dispatched occurrence")
    by_id = {call["id"]: call for call in record["calls"]}
    for call_id, declaration in review.calls.items():
        call = by_id[call_id]
        if call["tool"] in SCHEMAS and call["status"] == "completed":
            SCHEMAS[call["tool"]].model_validate(call["params"])
            expected_effect = registered_effects(call["tool"])
            if [
                effect.model_dump(mode="json") for effect in declaration.side_effects
            ] != expected_effect:
                raise ValueError(
                    "review side effect contradicts the registered tool contract"
                )
        if set(declaration.bindings) != set(call["params"]):
            raise ValueError(
                "review must cover every parameter, including unresolved ones"
            )
        if len(set(declaration.depends_on)) != len(declaration.depends_on):
            raise ValueError("duplicate declared dependency")
        if any(
            parent not in by_id or ids.index(parent) >= ids.index(call_id)
            for parent in declaration.depends_on
        ):
            raise ValueError(
                "dependency references an unknown, self or future occurrence"
            )
        for parameter, binding in declaration.bindings.items():
            if binding.kind == "unresolved":
                continue
            if binding.kind == "constant":
                if binding.path or binding.source_call_id is not None:
                    raise ValueError("constant cannot name a source")
                observed = binding.value
            elif binding.kind == "task_input":
                if not binding.path or binding.source_call_id is not None:
                    raise ValueError("task binding requires only an input path")
                observed = get_path(record["task"], binding.path)
            else:
                if binding.source_call_id not in declaration.depends_on:
                    raise ValueError(
                        "tool-output binding requires an explicitly declared dependency"
                    )
                source = by_id[binding.source_call_id]
                if source["status"] != "completed":
                    raise ValueError("failed call cannot supply resolved output")
                observed = get_path(source["output"], binding.path)
            if digest(observed) != digest(call["params"][parameter]):
                raise ValueError(
                    "declared binding does not match the recorded typed value"
                )
    # Exclusion is an explicit compilation decision, never deletion from evaluation.
    if review.decision == "exclude_from_compilation":
        return None
    if (
        not ids
        or record["ending"] != "model_finished"
        or any(
            call["status"] != "completed" or call["tool"] not in SCHEMAS
            for call in record["calls"]
        )
        or not any(call["tool"] == "update_ticket" for call in record["calls"])
    ):
        raise ValueError(
            "incomplete or failed recording must remain outside executable mining"
        )
    collector = make_collector(
        plan,
        case,
        model_id=record["model_requested"],
        scripted=record["scripted_model"],
    )
    collector.run_id = record["run_id"]
    collector.calls = record["calls"]
    collector.ending = record["ending"]
    # Import observations without replaying tool calls or trusting a stored normalized file.
    collector.simulator.customers = record["state_after"]["customers"]
    collector.simulator.orders = record["state_after"]["orders"]
    collector.simulator.tickets = record["state_after"]["tickets"]
    data = collector.normalized()
    for step in data.runs[0].steps:
        declaration = review.calls[step.id]
        step.depends_on = declaration.depends_on
        step.side_effects = declaration.side_effects
        step.metadata["dependency_review_required"] = False
        step.metadata["binding_declarations"] = {
            parameter: binding.model_dump(mode="json")
            for parameter, binding in declaration.bindings.items()
        }
        if declaration.alignment_key:
            step.metadata["alignment_key"] = declaration.alignment_key
    from .models import DatasetPartition

    data.partition = (
        DatasetPartition.COMPILE
        if case.partition == "compile"
        else DatasetPartition.TEST
    )
    data.metadata.update(
        import_review_status="complete",
        raw_sha256=review.raw_sha256,
        review_sha256=digest(review.model_dump(mode="json")),
        reviewer=review.reviewer,
        review_minutes=review.review_minutes,
        corpus_partition=case.partition,
        binding_resolution_still_required=True,
        plan_sha256=review.plan_sha256,
    )
    data.runs[0].metadata.update(
        raw_sha256=review.raw_sha256,
        review_sha256=digest(review.model_dump(mode="json")),
        collection_context=record["collection_context"],
    )
    # Revalidate graphs after applying declarations; the IR gate still needs ResolutionPlan.
    return TraceDataset.model_validate(data.model_dump(mode="json"))


def combine_reviewed(datasets: list[TraceDataset], dataset_id: str) -> TraceDataset:
    if not datasets:
        raise ValueError("no included reviewed recordings")
    roles = {data.metadata.get("corpus_partition") for data in datasets}
    plans = {data.metadata.get("plan_sha256") for data in datasets}
    if len(roles) != 1 or len(plans) != 1 or None in plans:
        raise ValueError("cannot combine different corpus partitions or plans")
    if any(
        data.metadata.get("import_review_status") != "complete" for data in datasets
    ):
        raise ValueError("cannot combine unreviewed recordings")
    return TraceDataset.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "partition": datasets[0].partition.value,
            "runs": [
                run.model_dump(mode="json") for data in datasets for run in data.runs
            ],
            "metadata": {
                "import_review_status": "complete",
                "corpus_partition": next(iter(roles)),
                "plan_sha256": next(iter(plans)),
                "binding_resolution_still_required": True,
                "review_minutes": sum(
                    data.metadata["review_minutes"] for data in datasets
                ),
            },
        }
    )


def declared_resolution(
    dataset: TraceDataset, candidate: CandidateDag
) -> ResolutionPlan:
    """Translate agreeing reviewer declarations, never resolve by value equality."""
    if (
        dataset.metadata.get("import_review_status") != "complete"
        or candidate.source_dataset_id != dataset.dataset_id
        or candidate.source_sha256
        != hashlib.sha256(canonical_json(dataset).encode()).hexdigest()
    ):
        raise ValueError("resolution requires the reviewed candidate source")
    calls = {(run.id, step.id): step for run in dataset.runs for step in run.steps}
    occurrence_nodes = {
        (ref.run_id, ref.step_id): node.id
        for node in candidate.nodes
        for ref in node.occurrences
    }
    overrides, effects = [], []
    for node in candidate.nodes:
        if node.alignment_status is AlignmentStatus.UNRESOLVED:
            continue
        members = [(ref, calls[(ref.run_id, ref.step_id)]) for ref in node.occurrences]
        for parameter in members[0][1].params:
            proposals = []
            for ref, step in members:
                raw = step.metadata.get("binding_declarations", {}).get(parameter)
                if raw is None or raw["kind"] == "unresolved":
                    break
                binding = {"kind": raw["kind"]}
                if raw["kind"] == "constant":
                    binding["value"] = raw["value"]
                elif raw["kind"] == "task_input":
                    binding["path"] = raw["path"]
                else:
                    binding["path"] = raw["path"]
                    binding["source_node_id"] = occurrence_nodes[
                        (ref.run_id, raw["source_call_id"])
                    ]
                proposals.append(binding)
            if (
                len(proposals) == len(members)
                and len({digest(item) for item in proposals}) == 1
            ):
                overrides.append(
                    {
                        "node_id": node.id,
                        "parameter": parameter,
                        "binding": proposals[0],
                    }
                )
        if any(
            effect.kind.value == "write"
            for _, step in members
            for effect in step.side_effects
        ):
            effects.append(node.id)
    outputs = [
        node.id
        for node in candidate.nodes
        if node.tool == "update_ticket"
        and node.alignment_status is AlignmentStatus.ALIGNED
    ]
    return ResolutionPlan.model_validate(
        {
            "binding_overrides": overrides,
            "confirmed_side_effect_nodes": effects,
            "output_node_ids": outputs if len(outputs) == 1 else [],
        }
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a complete Agent recording review"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("raw", type=Path)
    parser.add_argument("review", nargs="?", type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; no overwrite")
    if args.draft:
        if args.review is not None:
            parser.error("draft generation does not consume an approved review")
        template = draft_review(load_plan(args.plan), args.raw.read_bytes())
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
        return 0
    if args.review is None:
        parser.error("a completed review file is required, or use --draft")
    declaration = RecordingReview.model_validate(
        loads_json_document(args.review.read_text())
    )
    result = review_recording(load_plan(args.plan), args.raw.read_bytes(), declaration)
    if result is None:
        print(
            json.dumps(
                {
                    "decision": "exclude_from_compilation",
                    "retain_raw_for_evaluation": True,
                }
            )
        )
        return 0
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(result.model_dump_json(indent=2) + "\n")
    return 0


def build_main(argv=None) -> int:
    """Build inspection artifacts, retaining blockers rather than inventing resolutions."""
    from .candidate import mine_candidate_dag
    from .ir import build_workflow_ir

    parser = argparse.ArgumentParser(description="Compile included reviewed Agent runs")
    parser.add_argument("reviewed", nargs="+", type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("output directory already exists; no overwrite")
    dataset = combine_reviewed(
        [load_trace_dataset(path) for path in args.reviewed], args.dataset_id
    )
    if dataset.metadata["corpus_partition"] != "compile":
        parser.error("only the compile partition may build a workflow")
    candidate = mine_candidate_dag(dataset)
    resolution = declared_resolution(dataset, candidate)
    workflow = build_workflow_ir(dataset, candidate, resolution)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in (
        ("compile.json", dataset),
        ("candidate.json", candidate),
        ("resolution.json", resolution),
        ("workflow.json", workflow),
    ):
        with (args.output_dir / name).open("x", encoding="utf-8") as stream:
            stream.write(value.model_dump_json(indent=2) + "\n")
    print(json.dumps({"execution_blockers": workflow.execution_blockers()}))
    return 2 if workflow.execution_blockers() else 0


if __name__ == "__main__":
    raise SystemExit(main())

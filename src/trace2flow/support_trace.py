"""Strict adapter from standard support-Agent turns to Trace2Flow traces.

The adapter never infers dependency or side-effect semantics. An unreviewed
recording is useful for inspection but remains quarantined from candidate
mining. Promotion requires an exhaustive, hash-bound review of every call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .models import (
    DatasetPartition,
    RunProvenance,
    RunStatus,
    SideEffect,
    SideEffectKind,
    StepStatus,
    StrictModel,
    TraceDataset,
    TraceRun,
    TraceStep,
)


class RecordedSupportRequest(StrictModel):
    thread_id: str
    ticket_id: str
    authenticated_customer_id: str
    message: str
    channel: Literal["web", "app", "email"]
    locale: str


class RecordedSupportCall(StrictModel):
    id: str
    tool: str
    params: dict[str, JsonValue]
    status: Literal["completed", "failed"]
    output: JsonValue
    error_type: str | None
    state_changed: bool


class SupportAgentRecording(StrictModel):
    schema_version: Literal["support-agent-recording/1.0"]
    run_id: str
    request: RecordedSupportRequest
    model_requested: str
    model_snapshot_pinned: bool
    prompt_version: str
    system_prompt: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_contract_version: str
    environment: Literal["synthetic_local_support_backend"]
    contains_real_customer_data: Literal[False]
    ending: str
    model_calls: int = Field(ge=0)
    events: list[dict[str, JsonValue]]
    calls: list[RecordedSupportCall]
    state_before: dict[str, JsonValue]
    state_after: dict[str, JsonValue]
    elapsed_seconds: float = Field(ge=0)
    omitted: list[str]

    @model_validator(mode="after")
    def validate_identity(self) -> SupportAgentRecording:
        if self.request.thread_id.strip() != self.request.thread_id:
            raise ValueError("recorded thread_id must be trimmed")
        call_ids = [call.id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("recording call IDs must be unique")
        actual_prompt_hash = hashlib.sha256(self.system_prompt.encode()).hexdigest()
        if self.prompt_sha256 != actual_prompt_hash:
            raise ValueError("recording prompt hash does not match system prompt")
        return self


class SupportTurnRecording(StrictModel):
    schema_version: Literal["support-agent-turn/1.0"]
    status: Literal["completed", "approval_required", "error"]
    thread_id: str
    answer: str | None
    pending_actions: list[dict[str, JsonValue]]
    error_type: str | None
    trace: SupportAgentRecording

    @model_validator(mode="after")
    def validate_turn(self) -> SupportTurnRecording:
        if self.thread_id != self.trace.request.thread_id:
            raise ValueError("turn and trace thread IDs differ")
        if self.status == "completed" and self.trace.ending != "completed":
            raise ValueError("completed turn must contain a completed trace")
        return self


class SupportSessionRecording(StrictModel):
    schema_version: Literal["support-agent-session/1.0"]
    turns: list[SupportTurnRecording] = Field(min_length=1)


class SupportRecordingReview(StrictModel):
    """Exhaustive human/AI review; never generated from call order."""

    schema_version: Literal["support-recording-review/1.0"] = (
        "support-recording-review/1.0"
    )
    recording_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    reviewer_kind: Literal["human", "ai", "automated_test"]
    approved: Literal[True] = True
    dependencies: dict[str, list[str]]
    side_effects: dict[str, list[SideEffect]]
    alignment_keys: dict[str, str | None]


def support_recording_sha256(recording: SupportAgentRecording) -> str:
    payload = json.dumps(
        recording.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_review(
    recording: SupportAgentRecording, review: SupportRecordingReview
) -> None:
    expected_hash = support_recording_sha256(recording)
    if review.recording_sha256 != expected_hash:
        raise ValueError("review was produced for a different recording")
    call_ids = {call.id for call in recording.calls}
    for name, inventory in (
        ("dependencies", set(review.dependencies)),
        ("side_effects", set(review.side_effects)),
        ("alignment_keys", set(review.alignment_keys)),
    ):
        missing = sorted(call_ids - inventory)
        unknown = sorted(inventory - call_ids)
        if missing or unknown:
            raise ValueError(
                f"review {name} inventory mismatch; missing={missing}, unknown={unknown}"
            )
    positions = {call.id: index for index, call in enumerate(recording.calls)}
    for call in recording.calls:
        dependencies = review.dependencies[call.id]
        unknown = sorted(set(dependencies) - call_ids)
        if unknown:
            raise ValueError(
                f"review dependencies for '{call.id}' reference unknown calls: {unknown}"
            )
        if call.id in dependencies:
            raise ValueError(f"call '{call.id}' cannot depend on itself")
        future = sorted(
            dependency
            for dependency in dependencies
            if positions[dependency] >= positions[call.id]
        )
        if future:
            raise ValueError(
                f"call '{call.id}' cannot depend on calls that had not executed: {future}"
            )
        effects = review.side_effects[call.id]
        if call.state_changed and not any(
            effect.kind is SideEffectKind.WRITE for effect in effects
        ):
            raise ValueError(
                f"state-changing call '{call.id}' must declare a reviewed write"
            )


def normalize_support_turn(
    raw_turn: dict,
    *,
    dataset_id: str,
    source: str,
    partition: DatasetPartition = DatasetPartition.COMPILE,
    review: SupportRecordingReview | None = None,
) -> TraceDataset:
    """Normalize one complete turn; keep unreviewed semantics quarantined."""

    turn = SupportTurnRecording.model_validate(raw_turn)
    recording = turn.trace
    if not recording.calls:
        raise ValueError("zero-call support turns cannot enter the trace schema")
    reviewed = review is not None
    if review is not None:
        _validate_review(recording, review)

    steps: list[TraceStep] = []
    for call in recording.calls:
        effects = review.side_effects[call.id] if review else []
        metadata: dict[str, JsonValue] = {
            "recorded_error_type": call.error_type,
            "recorded_state_changed": call.state_changed,
            "semantic_review": "complete" if reviewed else "required",
        }
        if review and review.alignment_keys[call.id] is not None:
            metadata["declared_alignment_key"] = review.alignment_keys[call.id]
        steps.append(
            TraceStep(
                id=call.id,
                tool=call.tool,
                params=call.params,
                output=call.output,
                depends_on=review.dependencies[call.id] if review else [],
                status=(
                    StepStatus.COMPLETED
                    if call.status == "completed"
                    else StepStatus.FAILED
                ),
                side_effects=effects,
                metadata=metadata,
            )
        )

    run_status = {
        "completed": RunStatus.COMPLETED,
        "approval_required": RunStatus.PARTIAL,
        "error": RunStatus.FAILED,
    }[turn.status]
    inputs = turn.trace.request.model_dump(mode="json")
    run = TraceRun(
        id=recording.run_id,
        provenance=RunProvenance(
            kind="synthetic",
            source=source,
            source_run_id=recording.run_id,
            source_revision=recording.producer_sha256,
            task_group_id=recording.request.thread_id,
            execution_context="local_simulator",
            contains_real_customer_data=False,
        ),
        inputs=inputs,
        steps=steps,
        status=run_status,
        final_output=turn.answer,
        state_before=recording.state_before,
        state_after=recording.state_after,
        metadata={
            "recording_sha256": support_recording_sha256(recording),
            "prompt_sha256": recording.prompt_sha256,
            "prompt_version": recording.prompt_version,
            "producer_sha256": recording.producer_sha256,
            "tool_contract_version": recording.tool_contract_version,
            "model_requested": recording.model_requested,
            "model_snapshot_pinned": recording.model_snapshot_pinned,
            "model_calls": recording.model_calls,
            "elapsed_seconds": recording.elapsed_seconds,
            "omitted": recording.omitted,
            "contains_real_customer_data": False,
            "semantic_review": "complete" if reviewed else "required",
            "reviewer": review.reviewer if review else None,
            "reviewer_kind": review.reviewer_kind if review else None,
        },
    )
    return TraceDataset(
        schema_version="1.0",
        dataset_id=dataset_id,
        partition=partition,
        runs=[run],
        metadata={
            "adapter": "standard-support-agent/1.0",
            "import_review_status": "complete" if reviewed else "required",
            "synthetic": True,
            "contains_real_customer_data": False,
            "semantic_policy": (
                "explicit_review" if reviewed else "no_dependencies_or_effects_inferred"
            ),
        },
    )


def merge_support_datasets(
    datasets: list[TraceDataset], *, dataset_id: str
) -> TraceDataset:
    """Merge reviewed runs without weakening partition/provenance validation."""

    if not datasets:
        raise ValueError("at least one support dataset is required")
    partitions = {dataset.partition for dataset in datasets}
    if len(partitions) != 1:
        raise ValueError("support datasets must have one partition")
    if any(dataset.metadata.get("import_review_status") != "complete" for dataset in datasets):
        raise ValueError("all support datasets must have complete semantic review")
    if any(
        run.status is not RunStatus.COMPLETED
        or any(step.status is not StepStatus.COMPLETED for step in run.steps)
        for dataset in datasets
        for run in dataset.runs
    ):
        raise ValueError("only fully successful reviewed runs are promotion eligible")
    return TraceDataset(
        schema_version="1.0",
        dataset_id=dataset_id,
        partition=datasets[0].partition,
        runs=[run for dataset in datasets for run in dataset.runs],
        metadata={
            "adapter": "standard-support-agent/1.0",
            "import_review_status": "complete",
            "synthetic": True,
            "contains_real_customer_data": False,
            "semantic_policy": "explicit_review",
        },
    )


def normalize_support_session(
    raw_session: dict,
    *,
    dataset_id: str,
    source: str,
    partition: DatasetPartition = DatasetPartition.COMPILE,
    reviews: dict[str, SupportRecordingReview] | None = None,
) -> TraceDataset:
    """Normalize the final state of every run in a saved CLI session."""

    session = SupportSessionRecording.model_validate(raw_session)
    final_by_run: dict[str, SupportTurnRecording] = {}
    for turn in session.turns:
        final_by_run[turn.trace.run_id] = turn
    if reviews is not None:
        missing = sorted(set(final_by_run) - set(reviews))
        unknown = sorted(set(reviews) - set(final_by_run))
        if missing or unknown:
            raise ValueError(
                f"session review inventory mismatch; missing={missing}, unknown={unknown}"
            )
    datasets = [
        normalize_support_turn(
            turn.model_dump(mode="json"),
            dataset_id=f"{dataset_id}:{run_id}",
            source=source,
            partition=partition,
            review=reviews[run_id] if reviews else None,
        )
        for run_id, turn in sorted(final_by_run.items())
    ]
    if reviews is not None:
        return merge_support_datasets(datasets, dataset_id=dataset_id)
    return TraceDataset(
        schema_version="1.0",
        dataset_id=dataset_id,
        partition=partition,
        runs=[run for dataset in datasets for run in dataset.runs],
        metadata={
            "adapter": "standard-support-agent/1.0",
            "import_review_status": "required",
            "synthetic": True,
            "contains_real_customer_data": False,
            "semantic_policy": "no_dependencies_or_effects_inferred",
        },
    )

"""Conservative import of recorded tau-bench text simulations.

The adapter intentionally does not infer dependencies from message order or
decode string tool responses. A complete human review can supply occurrence
dependencies and side effects before the dataset is eligible for mining.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from .io import loads_json_document
from .models import (
    DatasetPartition,
    Identifier,
    RunProvenance,
    RunStatus,
    SideEffect,
    StepStatus,
    StrictModel,
    TraceDataset,
    TraceRun,
    TraceStep,
    json_compatible,
)

TAU_REPOSITORY = "sierra-research/tau2-bench"
TAU_IMPORT_SCHEMA = "tau-import-review/1.0"


class TauImportError(ValueError):
    """The source results or review artifact cannot be imported safely."""


class TauCallReview(StrictModel):
    """Human-reviewed semantics for one source tool-call occurrence."""

    depends_on: list[Identifier]
    side_effects: list[SideEffect] = Field(min_length=1)
    alignment_key: Identifier | None = None


class TauSimulationReview(StrictModel):
    """Complete call review for one source simulation."""

    calls: dict[Identifier, TauCallReview]


class TauImportReview(StrictModel):
    """Review boundary required before imported traces can be mined."""

    schema_version: Literal["tau-import-review/1.0"]
    reviewer: Identifier
    redaction_reviewed: bool
    simulations: dict[Identifier, TauSimulationReview]

    @model_validator(mode="after")
    def require_redaction_review(self) -> TauImportReview:
        if not self.redaction_reviewed:
            raise ValueError("redaction_reviewed must be true for a complete review")
        return self


_SENSITIVE_KEYS = {
    "address",
    "address1",
    "address2",
    "city",
    "customer_id",
    "email",
    "first_name",
    "full_name",
    "last_name",
    "name",
    "order_id",
    "payment_method_id",
    "phone",
    "postal_code",
    "reservation_id",
    "ticket_id",
    "transaction_id",
    "user_id",
    "zip",
    "zip_code",
}
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")


def _require_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TauImportError(f"{location} must be a JSON object")
    return value


def _require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise TauImportError(f"{location} must be a JSON array")
    return value


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TauImportError(f"{location} must be a string or integer identifier")
    result = str(value)
    if not result.strip():
        raise TauImportError(f"{location} cannot be empty")
    return result


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or lowered.endswith(("_id", "_ids"))


class _BenchmarkRedactor:
    """Stable type-preserving pseudonymization for public simulator records."""

    def __init__(self, dataset_id: str) -> None:
        self._salt = dataset_id
        self._tokens: dict[tuple[str, str], JsonValue] = {}
        self._string_replacements: dict[str, str] = {}

    def _token(self, key: str, value: JsonValue) -> JsonValue:
        serialized = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        lookup = (key.lower(), serialized)
        existing = self._tokens.get(lookup)
        if existing is not None:
            return existing
        digest = hashlib.sha256(
            f"{self._salt}\0{key.lower()}\0{serialized}".encode()
        ).hexdigest()
        label = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_") or "value"
        if isinstance(value, bool) or value is None:
            token: JsonValue = value
        elif isinstance(value, int):
            token = 1_000_000_000 + int(digest[:10], 16) % 8_000_000_000
        elif isinstance(value, float):
            token = float(1_000_000_000 + int(digest[:10], 16) % 8_000_000_000)
        elif isinstance(value, str):
            token = f"<{label}_{digest[:10]}>"
            if value:
                self._string_replacements[value] = token
        else:
            return value
        self._tokens[lookup] = token
        return token

    def collect(self, value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                if isinstance(child_key, str):
                    self.collect(child, child_key)
            return
        if isinstance(value, list):
            for child in value:
                self.collect(child, key)
            return
        if (
            _is_sensitive_key(key)
            and isinstance(value, (str, int, float))
            and not isinstance(value, bool)
        ):
            self._token(key, json_compatible(value))

    def collect_opaque_tool_output(self, value: str) -> None:
        """Tokenize an unstructured tool result whose sensitive fields are unknown."""

        if value:
            self._token("tool_output", value)

    def redact_string(self, value: str) -> str:
        redacted = value
        for original, replacement in sorted(
            self._string_replacements.items(), key=lambda item: len(item[0]), reverse=True
        ):
            redacted = redacted.replace(original, replacement)
        redacted = _EMAIL_RE.sub("<email_redacted>", redacted)
        redacted = _PHONE_RE.sub("<phone_redacted>", redacted)
        return redacted

    def redact(self, value: Any, key: str = "") -> JsonValue:
        if isinstance(value, dict):
            return {
                str(child_key): self.redact(child, str(child_key))
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [self.redact(child, key) for child in value]
        compatible = json_compatible(value)
        if (
            _is_sensitive_key(key)
            and isinstance(value, (str, int, float))
            and not isinstance(value, bool)
        ):
            return self._token(key, compatible)
        if isinstance(value, str):
            return self.redact_string(value)
        return compatible


def _tool_messages(messages: list[Any]) -> dict[str, Mapping[str, Any]]:
    results: dict[str, Mapping[str, Any]] = {}
    for index, raw_message in enumerate(messages):
        message = _require_mapping(raw_message, f"messages[{index}]")
        candidates: list[Any]
        if "tool_messages" in message:
            candidates = _require_list(
                message.get("tool_messages"), f"messages[{index}].tool_messages"
            )
        elif message.get("role") == "tool":
            candidates = [message]
        else:
            continue
        for candidate in candidates:
            tool_message = _require_mapping(candidate, f"messages[{index}].tool_message")
            call_id = _identifier(tool_message.get("id"), "tool message id")
            if call_id in results:
                raise TauImportError(f"duplicate tool result id: {call_id}")
            results[call_id] = tool_message
    return results


def _assistant_calls(messages: list[Any]) -> list[tuple[str, str, dict[str, Any], Any]]:
    calls: list[tuple[str, str, dict[str, Any], Any]] = []
    seen: set[str] = set()
    for index, raw_message in enumerate(messages):
        message = _require_mapping(raw_message, f"messages[{index}]")
        if message.get("role") != "assistant":
            continue
        raw_calls = message.get("tool_calls")
        if raw_calls is None:
            continue
        for raw_call in _require_list(raw_calls, f"messages[{index}].tool_calls"):
            call = _require_mapping(raw_call, f"messages[{index}].tool_call")
            if call.get("requestor", "assistant") != "assistant":
                continue
            call_id = _identifier(call.get("id"), "tool call id")
            if call_id in seen:
                raise TauImportError(f"duplicate assistant tool call id: {call_id}")
            seen.add(call_id)
            name = _identifier(call.get("name"), f"tool call {call_id} name")
            arguments = dict(
                _require_mapping(
                    call.get("arguments"), f"tool call {call_id} arguments"
                )
            )
            calls.append((call_id, name, arguments, message.get("turn_idx", index)))
    return calls


def _last_assistant_text(messages: list[Any], redactor: _BenchmarkRedactor) -> JsonValue:
    for raw_message in reversed(messages):
        message = _require_mapping(raw_message, "message")
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str):
            return redactor.redact_string(content)
    return None


def _run_status(termination_reason: Any) -> RunStatus:
    if termination_reason in {"user_stop", "agent_stop"}:
        return RunStatus.COMPLETED
    if termination_reason in {
        "agent_error",
        "user_error",
        "infrastructure_error",
        "unexpected_error",
    }:
        return RunStatus.FAILED
    return RunStatus.PARTIAL


def _reward(simulation: Mapping[str, Any]) -> JsonValue:
    reward_info = simulation.get("reward_info")
    if not isinstance(reward_info, dict):
        return None
    return json_compatible(reward_info.get("reward"))


def _validate_review_coverage(
    review: TauImportReview,
    simulation_id: str,
    source_call_ids: list[str],
) -> TauSimulationReview:
    simulation_review = review.simulations.get(simulation_id)
    if simulation_review is None:
        raise TauImportError(f"review is missing simulation: {simulation_id}")
    expected = set(source_call_ids)
    actual = set(simulation_review.calls)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing calls: " + ", ".join(missing))
        if extra:
            details.append("unknown calls: " + ", ".join(extra))
        raise TauImportError(f"incomplete review for {simulation_id}: " + "; ".join(details))
    return simulation_review


def import_tau_results(
    source: Mapping[str, Any],
    *,
    dataset_id: str,
    simulation_ids: Iterable[str] = (),
    task_ids: Iterable[str] = (),
    successful_only: bool = False,
    review: TauImportReview | None = None,
) -> TraceDataset:
    """Convert selected half-duplex tau results without executing source content."""

    info = _require_mapping(source.get("info"), "info")
    revision = _identifier(info.get("git_commit"), "info.git_commit")
    environment = _require_mapping(info.get("environment_info"), "environment_info")
    domain = _identifier(environment.get("domain_name"), "environment_info.domain_name")
    if domain != "retail":
        raise TauImportError(
            f"this milestone accepts only the audited tau retail domain, got: {domain}"
        )

    task_map: dict[str, Mapping[str, Any]] = {}
    for index, raw_task in enumerate(_require_list(source.get("tasks"), "tasks")):
        task = _require_mapping(raw_task, f"tasks[{index}]")
        task_id = _identifier(task.get("id"), f"tasks[{index}].id")
        if task_id in task_map:
            raise TauImportError(f"duplicate task id: {task_id}")
        task_map[task_id] = task

    selected_simulations = set(simulation_ids)
    selected_tasks = set(task_ids)
    raw_simulations = _require_list(source.get("simulations"), "simulations")
    filtered: list[Mapping[str, Any]] = []
    for index, raw_simulation in enumerate(raw_simulations):
        simulation = _require_mapping(raw_simulation, f"simulations[{index}]")
        simulation_id = _identifier(simulation.get("id"), f"simulations[{index}].id")
        task_id = _identifier(
            simulation.get("task_id"), f"simulations[{index}].task_id"
        )
        if selected_simulations and simulation_id not in selected_simulations:
            continue
        if selected_tasks and task_id not in selected_tasks:
            continue
        if successful_only and _reward(simulation) != 1:
            continue
        filtered.append(simulation)

    if selected_simulations:
        found = {_identifier(item.get("id"), "simulation id") for item in filtered}
        missing = sorted(selected_simulations - found)
        if missing:
            raise TauImportError(
                "selected simulation ids were not found or failed filters: "
                + ", ".join(missing)
            )
    if not filtered:
        raise TauImportError("no simulations matched the import selection")

    redactor = _BenchmarkRedactor(dataset_id)
    for simulation in filtered:
        task_id = _identifier(simulation.get("task_id"), "simulation.task_id")
        task = task_map.get(task_id)
        if task is None:
            raise TauImportError(f"simulation references unknown task: {task_id}")
        redactor.collect(task)
        messages = _require_list(simulation.get("messages"), "simulation.messages")
        for _, _, arguments, _ in _assistant_calls(messages):
            redactor.collect(arguments)
        for tool_message in _tool_messages(messages).values():
            content = tool_message.get("content")
            if isinstance(content, str):
                try:
                    redactor.collect(loads_json_document(content))
                except ValueError:
                    redactor.collect_opaque_tool_output(content)

    runs: list[TraceRun] = []
    for simulation in filtered:
        simulation_id = _identifier(simulation.get("id"), "simulation.id")
        task_id = _identifier(simulation.get("task_id"), "simulation.task_id")
        task = task_map[task_id]
        messages = _require_list(simulation.get("messages"), "simulation.messages")
        source_calls = _assistant_calls(messages)
        if not source_calls:
            raise TauImportError(f"simulation has no assistant tool calls: {simulation_id}")
        result_by_id = _tool_messages(messages)
        source_ids = [item[0] for item in source_calls]
        simulation_review = (
            _validate_review_coverage(review, simulation_id, source_ids)
            if review is not None
            else None
        )
        step_id_by_source = {
            source_id: f"call_{index:03d}"
            for index, source_id in enumerate(source_ids, start=1)
        }
        source_position = {
            source_id: index for index, source_id in enumerate(source_ids)
        }

        steps: list[TraceStep] = []
        for source_id, name, arguments, turn_idx in source_calls:
            tool_result = result_by_id.get(source_id)
            call_review = (
                simulation_review.calls[source_id]
                if simulation_review is not None
                else None
            )
            depends_on = []
            side_effects = []
            metadata: dict[str, JsonValue] = {
                "observed_turn_index": json_compatible(turn_idx),
                "source_call_sha256": hashlib.sha256(
                    source_id.encode("utf-8")
                ).hexdigest(),
                "tool_output_representation": "tau_tool_message_content_string",
            }
            if call_review is not None:
                unknown = sorted(set(call_review.depends_on) - set(source_ids))
                if unknown:
                    raise TauImportError(
                        f"review for {simulation_id}:{source_id} references unknown "
                        "calls: " + ", ".join(unknown)
                    )
                non_predecessors = sorted(
                    dependency
                    for dependency in call_review.depends_on
                    if source_position[dependency] >= source_position[source_id]
                )
                if non_predecessors:
                    raise TauImportError(
                        f"review for {simulation_id}:{source_id} declares a "
                        "non-preceding dependency: " + ", ".join(non_predecessors)
                    )
                depends_on = [step_id_by_source[item] for item in call_review.depends_on]
                side_effects = [item.model_copy(deep=True) for item in call_review.side_effects]
                if call_review.alignment_key is not None:
                    metadata["alignment_key"] = call_review.alignment_key

            output: JsonValue = None
            failed = tool_result is None or bool(tool_result.get("error", False))
            if tool_result is None:
                metadata["missing_tool_result"] = True
            else:
                output = redactor.redact(tool_result.get("content"))
            steps.append(
                TraceStep(
                    id=step_id_by_source[source_id],
                    tool=name,
                    params=redactor.redact(arguments),
                    output=output,
                    depends_on=depends_on,
                    status=StepStatus.FAILED if failed else StepStatus.COMPLETED,
                    side_effects=side_effects,
                    metadata=metadata,
                )
            )

        user_scenario = task.get("user_scenario")
        instructions: Any = {}
        if isinstance(user_scenario, dict):
            instructions = user_scenario.get("instructions") or {}
        run_id = "tau_" + hashlib.sha256(simulation_id.encode("utf-8")).hexdigest()[:16]
        runs.append(
            TraceRun(
                id=run_id,
                provenance=RunProvenance(
                    kind="recorded",
                    source=TAU_REPOSITORY,
                    source_run_id=simulation_id,
                    source_revision=revision,
                    task_group_id=task_id,
                    execution_context="benchmark_simulator",
                    contains_real_customer_data=False,
                ),
                inputs={"user_scenario": redactor.redact(instructions)},
                steps=steps,
                status=_run_status(simulation.get("termination_reason")),
                final_output=_last_assistant_text(messages, redactor),
                state_before={},
                state_after={},
                metadata={
                    "domain": domain,
                    "final_output_source": "last_assistant_text_not_verified_task_result",
                    "reward": _reward(simulation),
                    "termination_reason": redactor.redact(
                        simulation.get("termination_reason")
                    ),
                    "trial": redactor.redact(simulation.get("trial")),
                    "state_snapshots": "unavailable_in_tau_results",
                },
            )
        )

    reviewed = review is not None
    return TraceDataset(
        schema_version="1.0",
        dataset_id=dataset_id,
        partition=DatasetPartition.UNSPECIFIED,
        runs=runs,
        metadata={
            "source_format": "tau3_text_results_json",
            "source_repository": TAU_REPOSITORY,
            "source_revision": revision,
            "source_domain": domain,
            "license": "MIT",
            "recording_claim": "recorded_execution_in_public_benchmark_simulator",
            "contains_real_customer_data": False,
            "dependency_evidence": (
                "explicit_human_review" if reviewed else "unavailable_call_order_only"
            ),
            "side_effect_evidence": (
                "explicit_human_review" if reviewed else "unavailable"
            ),
            "state_snapshot_evidence": "unavailable",
            "tool_outputs": "preserved_as_recorded_strings_after_redaction",
            "automatic_redaction": "type_preserving_structured_pseudonymization",
            "manual_redaction_review": "complete" if reviewed else "required",
            "import_review_status": "complete" if reviewed else "required",
            "reviewer": review.reviewer if review is not None else None,
            "dropped_source_fields": [
                "agent_cost",
                "audio",
                "policy_prompt",
                "provider_raw_data",
                "timestamps",
                "token_usage",
                "user_cost",
            ],
        },
    )


def load_tau_review(path: str | Path) -> TauImportReview:
    value = loads_json_document(Path(path).read_text(encoding="utf-8"))
    try:
        return TauImportReview.model_validate(value)
    except ValueError as exc:
        raise TauImportError(f"invalid tau import review: {exc}") from None


def load_tau_results(path: str | Path) -> Mapping[str, Any]:
    source_path = Path(path)
    if source_path.is_dir():
        source_path = source_path / "results.json"
    value = loads_json_document(source_path.read_text(encoding="utf-8"))
    return _require_mapping(value, "tau results")

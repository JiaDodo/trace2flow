"""Versioned, framework-independent models for recorded agent traces."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue, config=ConfigDict(strict=True))


class DatasetPartition(str, Enum):
    """Declared role of every complete run in a dataset."""

    UNSPECIFIED = "unspecified"
    COMPILE = "compile"
    TEST = "test"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SideEffectKind(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


class StrictModel(BaseModel):
    """Shared validation policy for the normalized trace schema."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SideEffect(StrictModel):
    """Observed external-state interaction made by one tool call."""

    kind: SideEffectKind = Field(strict=False)
    target: Identifier | None = None
    reversible: bool | None = None

    @model_validator(mode="after")
    def validate_target(self) -> SideEffect:
        if self.kind is SideEffectKind.NONE and self.target is not None:
            raise ValueError("a 'none' side effect cannot declare a target")
        if self.kind in (SideEffectKind.READ, SideEffectKind.WRITE) and self.target is None:
            raise ValueError(f"a '{self.kind.value}' side effect requires a target")
        if self.kind is not SideEffectKind.WRITE and self.reversible is not None:
            raise ValueError("only a 'write' side effect can declare reversibility")
        return self


class RunProvenance(StrictModel):
    """Origin of a complete task run, used to prevent renamed-run leakage."""

    kind: Literal["synthetic", "recorded"]
    source: Identifier
    source_run_id: Identifier
    source_revision: Identifier | None = None
    task_group_id: Identifier | None = None
    execution_context: Literal[
        "hand_authored",
        "benchmark_simulator",
        "local_simulator",
        "production",
    ] | None = None
    contains_real_customer_data: bool | None = None

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class TraceStep(StrictModel):
    """One distinct tool-call occurrence inside a task run."""

    id: Identifier
    tool: Identifier
    params: dict[str, JsonValue] = Field(default_factory=dict)
    output: JsonValue = None
    depends_on: list[Identifier] = Field(default_factory=list)
    spawned_by: Identifier | None = None
    status: StepStatus = Field(strict=False)
    side_effects: list[SideEffect] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("depends_on")
    @classmethod
    def validate_unique_dependencies(cls, value: list[str]) -> list[str]:
        duplicate_ids = sorted(
            item for item, count in Counter(value).items() if count > 1
        )
        if duplicate_ids:
            raise ValueError(
                "duplicate depends_on references: " + ", ".join(duplicate_ids)
            )
        return value


class TraceRun(StrictModel):
    """A complete task execution; this is the atomic dataset split unit."""

    id: Identifier
    provenance: RunProvenance
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    steps: list[TraceStep] = Field(min_length=1)
    status: RunStatus = Field(strict=False)
    final_output: JsonValue = None
    state_before: dict[str, JsonValue] = Field(default_factory=dict)
    state_after: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_step_graph(self) -> TraceRun:
        step_ids = [step.id for step in self.steps]
        duplicates = sorted(
            step_id for step_id, count in Counter(step_ids).items() if count > 1
        )
        if duplicates:
            raise ValueError("duplicate step ids: " + ", ".join(duplicates))

        known_ids = set(step_ids)
        dependency_map: dict[str, set[str]] = {}
        for step in self.steps:
            references = list(step.depends_on)
            if step.spawned_by is not None:
                references.append(step.spawned_by)
            unknown = sorted(set(references) - known_ids)
            if unknown:
                raise ValueError(
                    f"step '{step.id}' references unknown step(s): {', '.join(unknown)}"
                )
            if step.id in references:
                raise ValueError(f"step '{step.id}' cannot reference itself")
            dependency_map[step.id] = set(references)

        self._assert_acyclic(dependency_map)
        return self

    @staticmethod
    def _assert_acyclic(dependencies: dict[str, set[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"dependency cycle includes step '{step_id}'")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency_id in sorted(dependencies[step_id]):
                visit(dependency_id)
            visiting.remove(step_id)
            visited.add(step_id)

        for candidate in sorted(dependencies):
            visit(candidate)

    def occurrence_ids(self) -> list[str]:
        """Return stable run-qualified IDs without collapsing repeated tools."""

        return [f"{self.id}:{step.id}" for step in self.steps]


class TraceDataset(StrictModel):
    """The only normalized JSON trace envelope supported by Trace2Flow."""

    schema_version: Literal["1.0"]
    dataset_id: Identifier
    partition: DatasetPartition = Field(
        default=DatasetPartition.UNSPECIFIED,
        strict=False,
    )
    runs: list[TraceRun] = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> TraceDataset:
        run_ids = [run.id for run in self.runs]
        duplicate_ids = sorted(
            run_id for run_id, count in Counter(run_ids).items() if count > 1
        )
        if duplicate_ids:
            raise ValueError("duplicate run ids: " + ", ".join(duplicate_ids))

        fingerprints = [run.provenance.fingerprint() for run in self.runs]
        duplicate_fingerprints = sorted(
            value for value, count in Counter(fingerprints).items() if count > 1
        )
        if duplicate_fingerprints:
            raise ValueError(
                "duplicate run provenance fingerprints: "
                + ", ".join(duplicate_fingerprints)
            )
        return self

    def run_by_id(self, run_id: str) -> TraceRun:
        for run in self.runs:
            if run.id == run_id:
                return run
        raise KeyError(run_id)


def json_compatible(value: Any) -> JsonValue:
    """Validate an arbitrary Python value as strict JSON without coercion."""

    return _JSON_VALUE_ADAPTER.validate_python(value)

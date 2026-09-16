"""Audited inventory builder for the public tau3-bench retail dataset.

This module inventories benchmark *tasks*.  It does not pretend that task
oracles are recorded Agent trajectories and it never exports the sealed test
oracles.  Actual model/tool runs still have to be collected and reviewed by
the existing :mod:`trace2flow.tau_import` boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from .models import Identifier, StrictModel

TAU3_REPOSITORY = "https://github.com/sierra-research/tau2-bench"
PINNED_TAU3_COMMIT = "2174a603f6d014ef94473ffa95957f6ce27100db"
MANIFEST_SCHEMA = "tau3-retail-corpus-manifest/1.0"
RETAIL_DATA_PATH = Path("data/tau2/domains/retail")
PINNED_FILE_HASHES = {
    "LICENSE": "e67c5aa0074dfcaefd3c3a1aedb94cb539234aecd15d5a972574e3200e6252fe",
    "data/tau2/domains/retail/db.json": (
        "413a65160adbdb5fde0ffc0015c49b6d70250b10c18128de169b597af7766765"
    ),
    "data/tau2/domains/retail/policy.md": (
        "2c9652afbce57d6e087768d37cda64d31c53d50b3e3225cfdb791bac66466467"
    ),
    "data/tau2/domains/retail/split_tasks.json": (
        "ed0580ec52575b63fbf76568af42490da6ee7783ecb4aa81af46961291358f20"
    ),
    "data/tau2/domains/retail/tasks.json": (
        "8e03ebce7901bd6218e7a7dc3105faa9324091a68058f7fe61c65262868812e8"
    ),
}

WRITE_TOOLS = frozenset(
    {
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_user_address",
        "return_delivered_order_items",
        "transfer_to_human_agents",
    }
)
# Task 105 was used for the provider integration pilot before this split was
# frozen.  Its complete entity-connected group is therefore development-only.
PREEXPOSED_DEVELOPMENT_TASK_IDS = frozenset({"105"})


class Tau3CorpusError(ValueError):
    """The source checkout or public split cannot be audited safely."""


class SourceFile(StrictModel):
    path: Identifier
    sha256: Identifier


class DevelopmentTask(StrictModel):
    """Train-side metadata safe to inspect while developing the pipeline."""

    task_id: Identifier
    role: Literal["compile", "development"]
    entity_group_sha256: Identifier
    source_task_sha256: Identifier
    action_count: int = Field(ge=0)
    action_names: list[Identifier]
    workflow_families: list[Identifier]
    reward_basis: list[Identifier]


class SealedTestInventory(StrictModel):
    """Test identities only; no instructions, actions, or assertions."""

    role: Literal["sealed_test"]
    task_count: int = Field(ge=1)
    task_ids: list[Identifier]
    oracle_fields_exported: Literal[False]


class Tau3RetailManifest(StrictModel):
    schema_version: Literal["tau3-retail-corpus-manifest/1.0"]
    dataset: Literal["tau3-bench/retail"]
    source_repository: Identifier
    source_commit: Identifier
    source_license: Literal["MIT"]
    source_files: list[SourceFile]
    data_claim: Literal["public_simulated_benchmark_tasks_not_agent_traces"]
    split_policy: Identifier
    task_count: int = Field(ge=1)
    official_train_count: int = Field(ge=1)
    compile_count: int = Field(ge=1)
    development_count: int = Field(ge=1)
    sealed_test: SealedTestInventory
    train_tasks: list[DevelopmentTask]
    limitations: list[Identifier]

    @model_validator(mode="after")
    def validate_inventory(self) -> Tau3RetailManifest:
        ids = [task.task_id for task in self.train_tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("train task ids must be unique")
        if set(ids) & set(self.sealed_test.task_ids):
            raise ValueError("official train and sealed-test task ids overlap")
        if len(ids) != self.official_train_count:
            raise ValueError("official_train_count does not match train inventory")
        if self.compile_count != sum(task.role == "compile" for task in self.train_tasks):
            raise ValueError("compile_count does not match train inventory")
        if self.development_count != sum(
            task.role == "development" for task in self.train_tasks
        ):
            raise ValueError("development_count does not match train inventory")
        if self.task_count != self.official_train_count + self.sealed_test.task_count:
            raise ValueError("task_count does not match partitions")
        group_roles: dict[str, set[str]] = defaultdict(set)
        for task in self.train_tasks:
            group_roles[task.entity_group_sha256].add(task.role)
        if any(len(roles) != 1 for roles in group_roles.values()):
            raise ValueError("an entity-connected group crosses compile/development")
        return self


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: JsonValue) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(payload)


def _load_json(path: Path) -> JsonValue:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Tau3CorpusError(f"cannot load {path}: {type(exc).__name__}") from exc


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise Tau3CorpusError(f"{location} must be a JSON object")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise Tau3CorpusError(f"{location} must be a JSON array")
    return value


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise Tau3CorpusError(f"{location} must be an identifier")
    result = str(value)
    if not result:
        raise Tau3CorpusError(f"{location} cannot be empty")
    return result


def _scalars(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        for child in value:
            yield from _scalars(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _scalars(child)
    elif isinstance(value, (str, int)) and not isinstance(value, bool):
        yield str(value)


def _entity_tokens(task: Mapping[str, Any]) -> set[str]:
    criteria = _mapping(task.get("evaluation_criteria"), "evaluation_criteria")
    actions = _list(criteria.get("actions"), "evaluation_criteria.actions")
    tokens: set[str] = set()
    for index, raw_action in enumerate(actions):
        action = _mapping(raw_action, f"actions[{index}]")
        arguments = _mapping(action.get("arguments"), f"actions[{index}].arguments")
        for key, value in arguments.items():
            if key.endswith(("_id", "_ids")):
                tokens.update(f"{key}:{item}" for item in _scalars(value))
    task_id = _identifier(task.get("id"), "task.id")
    return tokens or {f"task_id:{task_id}"}


def _connected_groups(tasks: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Group tasks transitively when any oracle entity identifier is shared."""

    task_ids = [_identifier(task.get("id"), "task.id") for task in tasks]
    parents = {task_id: task_id for task_id in task_ids}

    def find(task_id: str) -> str:
        parent = parents[task_id]
        if parent != task_id:
            parents[task_id] = find(parent)
        return parents[task_id]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    owners: dict[str, str] = {}
    for task in tasks:
        task_id = _identifier(task.get("id"), "task.id")
        for token in _entity_tokens(task):
            previous = owners.setdefault(token, task_id)
            union(task_id, previous)

    members: dict[str, list[str]] = defaultdict(list)
    for task_id in task_ids:
        members[find(task_id)].append(task_id)

    result: dict[str, list[str]] = {}
    for group in members.values():
        ordered = sorted(
            group,
            key=lambda value: (0, int(value)) if value.isdigit() else (1, value),
        )
        group_hash = sha256_bytes(
            ("tau3-retail-entity-group-v1\0" + "\0".join(ordered)).encode()
        )
        result[group_hash] = ordered
    return result


def _assign_roles(
    groups: Mapping[str, list[str]],
    target_compile: int,
    forced_development_task_ids: frozenset[str] = PREEXPOSED_DEVELOPMENT_TASK_IDS,
) -> dict[str, str]:
    """Select complete hash-ordered groups up to the declared compile target."""

    roles: dict[str, str] = {}
    compile_count = 0
    for group_hash, task_ids in sorted(groups.items()):
        if set(task_ids) & forced_development_task_ids:
            roles[group_hash] = "development"
            continue
        role = (
            "compile"
            if compile_count + len(task_ids) <= target_compile
            else "development"
        )
        roles[group_hash] = role
        if role == "compile":
            compile_count += len(task_ids)
    if compile_count == 0 or compile_count == sum(map(len, groups.values())):
        raise Tau3CorpusError("entity grouping did not produce two usable train roles")
    return roles


def _git_revision(source_root: Path) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Tau3CorpusError("source root is not a readable git checkout") from exc
    return process.stdout.strip()


def audit_source(source_root: Path) -> list[SourceFile]:
    revision = _git_revision(source_root)
    if revision != PINNED_TAU3_COMMIT:
        raise Tau3CorpusError(
            f"tau3 source revision mismatch: expected {PINNED_TAU3_COMMIT}, got {revision}"
        )
    files: list[SourceFile] = []
    for relative, expected_hash in sorted(PINNED_FILE_HASHES.items()):
        path = source_root / relative
        try:
            actual_hash = sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise Tau3CorpusError(f"cannot read pinned source file: {relative}") from exc
        if actual_hash != expected_hash:
            raise Tau3CorpusError(f"pinned source file hash mismatch: {relative}")
        files.append(SourceFile(path=relative, sha256=actual_hash))
    license_text = (source_root / "LICENSE").read_text(encoding="utf-8")
    if "MIT License" not in license_text:
        raise Tau3CorpusError("pinned source license is not MIT")
    return files


def build_manifest(
    tasks_document: JsonValue,
    split_document: JsonValue,
    source_files: list[SourceFile],
) -> Tau3RetailManifest:
    tasks_raw = _list(tasks_document, "tasks")
    tasks = [_mapping(task, f"tasks[{index}]") for index, task in enumerate(tasks_raw)]
    by_id: dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        task_id = _identifier(task.get("id"), "task.id")
        if task_id in by_id:
            raise Tau3CorpusError(f"duplicate task id: {task_id}")
        by_id[task_id] = task

    split = _mapping(split_document, "split_tasks")
    train_ids = [_identifier(item, "split.train") for item in _list(split.get("train"), "split.train")]
    test_ids = [_identifier(item, "split.test") for item in _list(split.get("test"), "split.test")]
    base_ids = [_identifier(item, "split.base") for item in _list(split.get("base"), "split.base")]
    if len(train_ids) != len(set(train_ids)) or len(test_ids) != len(set(test_ids)):
        raise Tau3CorpusError("official partitions contain duplicate task ids")
    if set(train_ids) & set(test_ids):
        raise Tau3CorpusError("official train and test partitions overlap")
    if set(base_ids) != set(train_ids) | set(test_ids):
        raise Tau3CorpusError("official base partition is not train + test")
    if set(base_ids) != set(by_id):
        raise Tau3CorpusError("tasks.json does not match the official base partition")
    if (len(tasks), len(train_ids), len(test_ids)) != (114, 74, 40):
        raise Tau3CorpusError("unexpected pinned retail task counts")

    train_tasks = [by_id[task_id] for task_id in train_ids]
    groups = _connected_groups(train_tasks)
    roles = _assign_roles(groups, target_compile=48)
    task_group = {
        task_id: group_hash
        for group_hash, task_ids in groups.items()
        for task_id in task_ids
    }

    inventory: list[DevelopmentTask] = []
    for task_id in sorted(train_ids, key=int):
        task = by_id[task_id]
        criteria = _mapping(task.get("evaluation_criteria"), "evaluation_criteria")
        actions = _list(criteria.get("actions"), "evaluation_criteria.actions")
        action_names = [
            _identifier(_mapping(action, "action").get("name"), "action.name")
            for action in actions
        ]
        reward_basis = [
            _identifier(item, "reward_basis")
            for item in _list(criteria.get("reward_basis"), "reward_basis")
        ]
        families = sorted(set(action_names) & WRITE_TOOLS) or ["no_write"]
        group_hash = task_group[task_id]
        inventory.append(
            DevelopmentTask(
                task_id=task_id,
                role=roles[group_hash],
                entity_group_sha256=group_hash,
                source_task_sha256=_canonical_hash(task),
                action_count=len(actions),
                action_names=action_names,
                workflow_families=families,
                reward_basis=reward_basis,
            )
        )

    compile_count = sum(task.role == "compile" for task in inventory)
    return Tau3RetailManifest(
        schema_version=MANIFEST_SCHEMA,
        dataset="tau3-bench/retail",
        source_repository=TAU3_REPOSITORY,
        source_commit=PINNED_TAU3_COMMIT,
        source_license="MIT",
        source_files=source_files,
        data_claim="public_simulated_benchmark_tasks_not_agent_traces",
        split_policy=(
            "official train/test; test oracle sealed; train entity-connected groups "
            "assigned deterministically to compile/development; pre-exposed pilot "
            "task groups forced to development"
        ),
        task_count=len(tasks),
        official_train_count=len(train_ids),
        compile_count=compile_count,
        development_count=len(inventory) - compile_count,
        sealed_test=SealedTestInventory(
            role="sealed_test",
            task_count=len(test_ids),
            task_ids=sorted(test_ids, key=int),
            oracle_fields_exported=False,
        ),
        train_tasks=inventory,
        limitations=[
            "Task specifications and action oracles are not observed Agent trajectories.",
            "Official train and test partitions reuse simulated entities; the test oracle remains sealed but entity isolation is not claimed.",
            "Compile/development roles prevent shared-entity groups from crossing those train-side roles.",
            "No model accuracy, token reduction, latency, cost, or workflow benefit follows from this inventory alone.",
        ],
    )


def build_manifest_from_checkout(source_root: Path) -> Tau3RetailManifest:
    source_files = audit_source(source_root)
    data_root = source_root / RETAIL_DATA_PATH
    return build_manifest(
        _load_json(data_root / "tasks.json"),
        _load_json(data_root / "split_tasks.json"),
        source_files,
    )


def manifest_json(manifest: Tau3RetailManifest) -> str:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def write_manifest_exclusive(manifest: Tau3RetailManifest, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(manifest_json(manifest))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit and inventory the pinned public tau3 retail dataset"
    )
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest_from_checkout(args.source_root)
        write_manifest_exclusive(manifest, args.output)
    except (Tau3CorpusError, FileExistsError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "compile": manifest.compile_count,
                "development": manifest.development_count,
                "sealed_test": manifest.sealed_test.task_count,
                "source_commit": manifest.source_commit,
                "tasks": manifest.task_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

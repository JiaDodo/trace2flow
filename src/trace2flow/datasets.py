"""Run-level dataset partitioning and leakage checks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import DatasetPartition, TraceDataset, TraceRun


class DatasetLeakageError(ValueError):
    """Compilation and test partitions contain the same complete task run."""


@dataclass(frozen=True)
class DatasetSplit:
    compile: TraceDataset
    test: TraceDataset


def _copy_partition(
    dataset: TraceDataset,
    *,
    suffix: str,
    partition: DatasetPartition,
    runs: list[TraceRun],
) -> TraceDataset:
    metadata = dict(dataset.metadata)
    metadata["parent_dataset_id"] = dataset.dataset_id
    payload = dataset.model_dump(mode="python")
    payload.update(
        dataset_id=f"{dataset.dataset_id}:{suffix}",
        partition=partition,
        runs=[run.model_dump(mode="python") for run in runs],
        metadata=metadata,
    )
    return TraceDataset.model_validate(payload)


def split_by_test_run_ids(
    dataset: TraceDataset, test_run_ids: Iterable[str]
) -> DatasetSplit:
    """Deterministically split whole runs using explicit test run IDs."""

    selected = set(test_run_ids)
    if not selected:
        raise ValueError("at least one test run id is required")

    known = {run.id for run in dataset.runs}
    unknown = sorted(selected - known)
    if unknown:
        raise KeyError("unknown test run ids: " + ", ".join(unknown))

    compile_runs = [run for run in dataset.runs if run.id not in selected]
    test_runs = [run for run in dataset.runs if run.id in selected]
    if not compile_runs:
        raise ValueError("the compile partition cannot be empty")

    result = DatasetSplit(
        compile=_copy_partition(
            dataset,
            suffix="compile",
            partition=DatasetPartition.COMPILE,
            runs=compile_runs,
        ),
        test=_copy_partition(
            dataset,
            suffix="test",
            partition=DatasetPartition.TEST,
            runs=test_runs,
        ),
    )
    assert_disjoint(result.compile, result.test)
    return result


def split_by_test_group_ids(
    dataset: TraceDataset, test_group_ids: Iterable[str]
) -> DatasetSplit:
    """Split whole source-task groups so trials of one task cannot leak."""

    selected = set(test_group_ids)
    if not selected:
        raise ValueError("at least one test group id is required")

    ungrouped = sorted(
        run.id for run in dataset.runs if run.provenance.task_group_id is None
    )
    if ungrouped:
        raise ValueError(
            "group splitting requires provenance.task_group_id on every run: "
            + ", ".join(ungrouped)
        )

    known = {run.provenance.task_group_id for run in dataset.runs}
    unknown = sorted(selected - known)
    if unknown:
        raise KeyError("unknown test group ids: " + ", ".join(unknown))

    compile_runs = [
        run for run in dataset.runs if run.provenance.task_group_id not in selected
    ]
    test_runs = [
        run for run in dataset.runs if run.provenance.task_group_id in selected
    ]
    if not compile_runs:
        raise ValueError("the compile partition cannot be empty")

    result = DatasetSplit(
        compile=_copy_partition(
            dataset,
            suffix="compile",
            partition=DatasetPartition.COMPILE,
            runs=compile_runs,
        ),
        test=_copy_partition(
            dataset,
            suffix="test",
            partition=DatasetPartition.TEST,
            runs=test_runs,
        ),
    )
    assert_disjoint(result.compile, result.test)
    return result


def assert_disjoint(compile_data: TraceDataset, test_data: TraceDataset) -> None:
    """Reject overlap by visible run ID or stable source provenance."""

    compile_ids = {run.id for run in compile_data.runs}
    test_ids = {run.id for run in test_data.runs}
    duplicate_ids = sorted(compile_ids & test_ids)
    if duplicate_ids:
        raise DatasetLeakageError("overlapping run ids: " + ", ".join(duplicate_ids))

    compile_provenance = {
        run.provenance.fingerprint(): run.id for run in compile_data.runs
    }
    test_provenance = {run.provenance.fingerprint(): run.id for run in test_data.runs}
    duplicate_fingerprints = sorted(set(compile_provenance) & set(test_provenance))
    if duplicate_fingerprints:
        pairs = [
            f"{compile_provenance[value]} <-> {test_provenance[value]} ({value})"
            for value in duplicate_fingerprints
        ]
        raise DatasetLeakageError(
            "overlapping run provenance fingerprints: " + "; ".join(pairs)
        )

    def grouped_runs(dataset: TraceDataset) -> dict[tuple[str, str], list[str]]:
        result: dict[tuple[str, str], list[str]] = {}
        for run in dataset.runs:
            group_id = run.provenance.task_group_id
            if group_id is not None:
                result.setdefault((run.provenance.source, group_id), []).append(run.id)
        return result

    compile_groups = grouped_runs(compile_data)
    test_groups = grouped_runs(test_data)
    duplicate_groups = sorted(set(compile_groups) & set(test_groups))
    if duplicate_groups:
        pairs = [
            f"{source}:{group_id} "
            f"({','.join(sorted(compile_groups[(source, group_id)]))} <-> "
            f"{','.join(sorted(test_groups[(source, group_id)]))})"
            for source, group_id in duplicate_groups
        ]
        raise DatasetLeakageError(
            "overlapping source task groups: " + "; ".join(pairs)
        )

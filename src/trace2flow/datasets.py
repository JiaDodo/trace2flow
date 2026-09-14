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

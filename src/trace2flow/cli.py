"""Local CLI for M1 trace validation, partitioning, and ASP adaptation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .asp import to_asp
from .datasets import DatasetLeakageError, split_by_test_run_ids
from .io import TraceFormatError, dump_trace_dataset, load_trace_dataset


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trace2flow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="validate a normalized JSON trace and optionally rewrite canonically",
    )
    validate.add_argument("input", type=Path)
    validate.add_argument("--output", type=Path)

    split = subparsers.add_parser(
        "split",
        help="split complete runs into compile and test datasets",
    )
    split.add_argument("input", type=Path)
    split.add_argument("--test-run-id", action="append", required=True)
    split.add_argument("--compile-output", type=Path, required=True)
    split.add_argument("--test-output", type=Path, required=True)

    asp = subparsers.add_parser(
        "to-asp",
        help="adapt a normalized JSON trace to the upstream ASP input subset",
    )
    asp.add_argument("input", type=Path)
    asp.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        dataset = load_trace_dataset(args.input)
        if args.command == "validate":
            if args.output is not None:
                dump_trace_dataset(dataset, args.output)
            print(
                json.dumps(
                    {
                        "dataset_id": dataset.dataset_id,
                        "partition": dataset.partition.value,
                        "runs": len(dataset.runs),
                        "steps": sum(len(run.steps) for run in dataset.runs),
                        "valid": True,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "split":
            split = split_by_test_run_ids(dataset, args.test_run_id)
            dump_trace_dataset(split.compile, args.compile_output)
            dump_trace_dataset(split.test, args.test_output)
            print(
                json.dumps(
                    {
                        "compile_runs": len(split.compile.runs),
                        "test_runs": len(split.test.runs),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "to-asp":
            bundle = to_asp(dataset)
            bundle.write(args.output)
            print(
                json.dumps(
                    {
                        "parameter_encoding": bundle.parameter_encoding,
                        "runs": len(dataset.runs),
                        "source_sha256": bundle.source_sha256,
                    },
                    sort_keys=True,
                )
            )
            return 0
    except (OSError, TraceFormatError, DatasetLeakageError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2

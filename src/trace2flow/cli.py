"""Local CLI for trace validation, upstream adaptation, and candidate mining."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .asp import to_asp
from .candidate import CandidateDag, candidate_json, mine_candidate_dag
from .datasets import (
    DatasetLeakageError,
    split_by_test_group_ids,
    split_by_test_run_ids,
)
from .evaluation import evaluate_structure, structural_report_json
from .io import TraceFormatError, dump_trace_dataset, load_trace_dataset
from .ir import (
    ResolutionPlan,
    build_workflow_ir,
    loads_workflow_ir,
    workflow_ir_json,
)
from .prefect_export import PrefectExportError, export_prefect
from .retail_simulation import (
    load_retail_suite,
    retail_verification_report_json,
    verify_retail_workflow,
)
from .simulation import verification_report_json, verify_workflow
from .tau_import import (
    TauImportError,
    import_tau_results,
    load_tau_results,
    load_tau_review,
)
from .upstream import RuleProfile, UpstreamCompilationError


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
    split_selector = split.add_mutually_exclusive_group(required=True)
    split_selector.add_argument("--test-run-id", action="append")
    split_selector.add_argument(
        "--test-group-id",
        action="append",
        help="hold out every run with this provenance task_group_id",
    )
    split.add_argument("--compile-output", type=Path, required=True)
    split.add_argument("--test-output", type=Path, required=True)

    tau_import = subparsers.add_parser(
        "import-tau",
        help="quarantine and normalize selected tau retail text simulations",
    )
    tau_import.add_argument("input", type=Path, help="tau results.json or its directory")
    tau_import.add_argument("--dataset-id", required=True)
    tau_selector = tau_import.add_mutually_exclusive_group(required=True)
    tau_selector.add_argument("--simulation-id", action="append")
    tau_selector.add_argument("--task-id", action="append")
    tau_selector.add_argument("--all", action="store_true")
    tau_import.add_argument("--successful-only", action="store_true")
    tau_import.add_argument("--review", type=Path)
    tau_import.add_argument("--output", type=Path, required=True)

    asp = subparsers.add_parser(
        "to-asp",
        help="adapt a normalized JSON trace to the upstream ASP input subset",
    )
    asp.add_argument("input", type=Path)
    asp.add_argument("--output", type=Path, required=True)

    mine = subparsers.add_parser(
        "mine",
        help="mine an evidence-bearing candidate DAG from compile-partition traces",
    )
    mine.add_argument("input", type=Path)
    mine.add_argument("--output", type=Path, required=True)
    mine.add_argument(
        "--rule-profile",
        choices=[profile.value for profile in RuleProfile],
        default=RuleProfile.STRICT.value,
    )

    build_ir = subparsers.add_parser(
        "build-ir",
        help="build framework-independent Workflow IR from traces and a candidate DAG",
    )
    build_ir.add_argument("input", type=Path)
    build_ir.add_argument("--candidate", type=Path, required=True)
    build_ir.add_argument("--resolution", type=Path)
    build_ir.add_argument("--output", type=Path, required=True)

    prefect = subparsers.add_parser(
        "export-prefect",
        help="export executable Prefect source after safety and registry checks",
    )
    prefect.add_argument("input", type=Path, help="workflow-ir/1.0 JSON")
    prefect.add_argument("--registered-tool", action="append", required=True)
    prefect.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser(
        "verify",
        help="verify a resolved workflow in the independent local simulator",
    )
    verify.add_argument("input", type=Path, help="workflow-ir/1.0 JSON")
    verify.add_argument("--compile", type=Path, required=True)
    verify.add_argument("--test", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)

    verify_retail = subparsers.add_parser(
        "verify-retail",
        help="verify the reviewed retail workflow shape in a fresh local simulator",
    )
    verify_retail.add_argument("input", type=Path, help="workflow-ir/1.0 JSON")
    verify_retail.add_argument("--cases", type=Path, required=True)
    verify_retail.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser(
        "evaluate-structure",
        help="compare a candidate DAG with disjoint held-out trace structure",
    )
    evaluate.add_argument("input", type=Path, help="candidate-dag/1.0 JSON")
    evaluate.add_argument("--compile", type=Path, required=True)
    evaluate.add_argument("--test", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "evaluate-structure":
            candidate = CandidateDag.model_validate_json(
                args.input.read_text(encoding="utf-8")
            )
            report = evaluate_structure(
                candidate,
                load_trace_dataset(args.compile),
                load_trace_dataset(args.test),
            )
            args.output.write_text(structural_report_json(report), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "all_runs_structurally_covered": (
                            report.all_runs_structurally_covered
                        ),
                        "candidate_edges": report.candidate_edges,
                        "candidate_nodes": report.candidate_nodes,
                        "covered_runs": report.covered_runs,
                        "execution_equivalence_claimed": (
                            report.execution_equivalence_claimed
                        ),
                        "test_runs": report.test_runs,
                        "validation_scope": report.validation_scope,
                    },
                    sort_keys=True,
                )
            )
            return 0 if report.all_runs_structurally_covered else 1

        if args.command == "import-tau":
            review = load_tau_review(args.review) if args.review is not None else None
            dataset = import_tau_results(
                load_tau_results(args.input),
                dataset_id=args.dataset_id,
                simulation_ids=args.simulation_id or (),
                task_ids=args.task_id or (),
                successful_only=args.successful_only,
                review=review,
            )
            dump_trace_dataset(dataset, args.output)
            print(
                json.dumps(
                    {
                        "dataset_id": dataset.dataset_id,
                        "import_review_status": dataset.metadata[
                            "import_review_status"
                        ],
                        "recording_claim": dataset.metadata["recording_claim"],
                        "runs": len(dataset.runs),
                        "steps": sum(len(run.steps) for run in dataset.runs),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "export-prefect":
            workflow = loads_workflow_ir(args.input.read_text(encoding="utf-8"))
            artifact = export_prefect(workflow, set(args.registered_tool))
            artifact.write(args.output)
            print(
                json.dumps(
                    {
                        "required_tools": list(artifact.required_tools),
                        "source_sha256": artifact.source_sha256,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "verify":
            workflow = loads_workflow_ir(args.input.read_text(encoding="utf-8"))
            compile_dataset = load_trace_dataset(args.compile)
            test_dataset = load_trace_dataset(args.test)
            report = verify_workflow(workflow, compile_dataset, test_dataset)
            args.output.write_text(verification_report_json(report), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "cases": len(report.cases),
                        "passed": report.passed,
                        "passed_cases": sum(
                            case.status == "passed" for case in report.cases
                        ),
                        "validation_scope": report.validation_scope,
                    },
                    sort_keys=True,
                )
            )
            return 0 if report.passed else 1

        if args.command == "verify-retail":
            workflow = loads_workflow_ir(args.input.read_text(encoding="utf-8"))
            report = verify_retail_workflow(
                workflow,
                load_retail_suite(args.cases),
            )
            args.output.write_text(
                retail_verification_report_json(report), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "cases": len(report.cases),
                        "passed": report.passed,
                        "passed_cases": sum(
                            case.status == "passed" for case in report.cases
                        ),
                        "recorded_response_replay_used": (
                            report.recorded_response_replay_used
                        ),
                        "validation_scope": report.validation_scope,
                    },
                    sort_keys=True,
                )
            )
            return 0 if report.passed else 1

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
            split = (
                split_by_test_run_ids(dataset, args.test_run_id)
                if args.test_run_id is not None
                else split_by_test_group_ids(dataset, args.test_group_id)
            )
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

        if args.command == "mine":
            candidate = mine_candidate_dag(
                dataset,
                RuleProfile(args.rule_profile),
            )
            args.output.write_text(candidate_json(candidate), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "accepted_edges": len(candidate.edges),
                        "candidate_nodes": len(candidate.nodes),
                        "source_runs": candidate.upstream.source_runs,
                        "unresolved_alignment_nodes": sum(
                            node.alignment_status.value == "unresolved"
                            for node in candidate.nodes
                        ),
                        "unresolved_dependencies": len(
                            candidate.unresolved_dependencies
                        ),
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "build-ir":
            candidate = CandidateDag.model_validate_json(
                args.candidate.read_text(encoding="utf-8")
            )
            resolution = (
                ResolutionPlan.model_validate_json(
                    args.resolution.read_text(encoding="utf-8")
                )
                if args.resolution is not None
                else None
            )
            workflow = build_workflow_ir(dataset, candidate, resolution)
            args.output.write_text(workflow_ir_json(workflow), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "blockers": len(workflow.execution_blockers()),
                        "edges": len(workflow.edges),
                        "nodes": len(workflow.nodes),
                        "unresolved_dependencies": workflow.unresolved_dependencies,
                    },
                    sort_keys=True,
                )
            )
            return 0
    except (
        OSError,
        TraceFormatError,
        TauImportError,
        DatasetLeakageError,
        PrefectExportError,
        UpstreamCompilationError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2

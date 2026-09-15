"""Reproducible local-model evaluation reports, never a provider-cost estimator."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import UTC
from pathlib import Path

from .agent_corpus import digest, load_plan, materialize, verify_freeze
from .agent_evaluation import evaluate_inventory, evaluate_workflow
from .io import load_trace_dataset, loads_json_document
from .ir import loads_workflow_ir
from .runtime import ToolRegistry
from .simulation import CustomerSupportSimulator, execute_local


def usage_metrics(record: dict) -> dict:
    events = [event for event in record["events"] if event["role"] == "assistant"]
    measured = [event["usage"] for event in events if event.get("usage") is not None]
    return {
        "model_calls": record["model_calls"],
        "tool_calls": len(record["calls"]),
        "failed_tool_calls": sum(
            call["status"] != "completed" for call in record["calls"]
        ),
        "usage_events": len(measured),
        "input_tokens": sum(item["input_tokens"] for item in measured),
        "output_tokens": sum(item["output_tokens"] for item in measured),
        "usage_complete": len(measured) == record["model_calls"],
        "agent_collection_elapsed_seconds": record["elapsed_seconds"],
    }


def measured_execution(plan, workflow, workflow_report: dict) -> list[dict]:
    """Repeat only local fixture execution, with a fresh simulator and counter."""
    by_id = {case.case_id: case for case in plan.cases}
    results = []
    for admission in workflow_report["results"]:
        if not admission["admitted"]:
            continue
        payload = materialize(by_id[admission["case_id"]])
        simulator = CustomerSupportSimulator(**payload["state_before"])
        original = simulator.registry()
        calls = []

        def counted(name, source_registry, call_inventory):
            def invoke(**params):
                call_inventory.append(name)
                return source_registry.invoke(name, params)

            return invoke

        registry = ToolRegistry(
            {name: counted(name, original, calls) for name in original.names}
        )
        started = time.perf_counter()
        error, output = None, None
        try:
            output = execute_local(workflow, payload["task"], registry).final_output
        except Exception as exc:  # noqa: BLE001 - preserve outcomes without leaking exception text
            error = type(exc).__name__
        elapsed = time.perf_counter() - started
        state = {
            "customers": simulator.customers,
            "orders": simulator.orders,
            "tickets": simulator.tickets,
        }
        results.append(
            {
                "case_id": admission["case_id"],
                "workflow_tool_calls": len(calls),
                "workflow_model_calls": 0,
                "workflow_execution_elapsed_seconds": elapsed,
                "independent_measurement_correct": error is None
                and digest(output) == digest(payload["oracle"]["expected_final_output"])
                and digest(state) == digest(payload["oracle"]["expected_state_after"]),
                "error": error,
            }
        )
    return results


def build_report(
    plan, records: list[dict], partition: str, workflow=None, compile_dataset=None
) -> dict:
    agent = evaluate_inventory(plan, records, partition)
    by_id = {record["task"]["task_id"]: record for record in records}
    usage = [
        {"case_id": case_id, **usage_metrics(record)}
        for case_id, record in sorted(by_id.items())
    ]
    report = {
        "schema_version": "agent-workflow-report/1.0",
        "scope": "recorded_model_calls_in_synthetic_local_business_environment",
        "partition": partition,
        "plan_sha256": digest(plan.model_dump(mode="json")),
        "agent": agent,
        "agent_usage": {
            "recorded_cases": len(usage),
            "model_calls": sum(item["model_calls"] for item in usage),
            "tool_calls": sum(item["tool_calls"] for item in usage),
            "failed_tool_calls": sum(item["failed_tool_calls"] for item in usage),
            "input_tokens": sum(item["input_tokens"] for item in usage),
            "output_tokens": sum(item["output_tokens"] for item in usage),
            "usage_complete": all(item["usage_complete"] for item in usage)
            and bool(usage),
            "results": usage,
        },
        "limitations": [
            "synthetic business tasks and deterministic classification/recommendation tools",
            "reviewed execution contract, not automatic lineage or branch discovery",
            "final customer-facing chat correctness is not measured",
            "Agent timer includes model/framework/collection; workflow timer is local execution only",
            "single trial per task, no statistical/generalization or production speedup claim",
            "token usage is measured where available; money/cost savings are not estimated",
        ],
    }
    if workflow is not None:
        workflow_report = evaluate_workflow(plan, workflow, partition, compile_dataset)
        measurements = measured_execution(plan, workflow, workflow_report)
        report["workflow"] = workflow_report
        matched = [
            {**item, "agent": usage_metrics(by_id[item["case_id"]])}
            for item in measurements
            if item["case_id"] in by_id
        ]
        report["matched_accepted_cases"] = {
            "cases": len(matched),
            "agent_model_calls": sum(item["agent"]["model_calls"] for item in matched),
            "workflow_model_calls": sum(
                item["workflow_model_calls"] for item in matched
            ),
            "agent_tool_calls": sum(item["agent"]["tool_calls"] for item in matched),
            "workflow_tool_calls": sum(item["workflow_tool_calls"] for item in matched),
            "agent_collection_elapsed_median_seconds": statistics.median(
                item["agent"]["agent_collection_elapsed_seconds"] for item in matched
            )
            if matched
            else None,
            "workflow_execution_elapsed_median_seconds": statistics.median(
                item["workflow_execution_elapsed_seconds"] for item in matched
            )
            if matched
            else None,
            "results": matched,
        }
        machine_review = all(
            run.metadata.get("reviewer_kind") == "ai"
            and run.metadata.get("review_minutes_kind")
            == "automated_contract_check_wall_time"
            for run in compile_dataset.runs
        )
        report["review_effort"] = {
            "reviewer_kind": "ai_declared_contract_and_automated_validation"
            if machine_review
            else "not_recorded",
            "human_review_minutes": 0 if machine_review else None,
            "ai_reasoning_review_minutes": None,
            "automated_contract_check_minutes": compile_dataset.metadata.get(
                "review_minutes"
            )
            if machine_review
            else None,
            "manual_ai_effort_measured": False,
        }
        report["workflow_sha256"] = digest(workflow.model_dump(mode="json"))
        report["compile_sha256"] = digest(compile_dataset.model_dump(mode="json"))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce Agent/workflow evidence without hiding pending cases"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("recordings", type=Path)
    parser.add_argument(
        "--partition", required=True, choices=["compile", "development", "test"]
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--compile", type=Path)
    parser.add_argument("--unlock-test", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; no overwrite")
    if args.partition == "test" and not args.unlock_test:
        parser.error("test results require --unlock-test")
    if (args.workflow is None) != (args.compile is None):
        parser.error("workflow and compile source must be provided together")
    plan = load_plan(args.plan)
    manifest = loads_json_document(args.manifest.read_text())
    verify_freeze(plan, manifest)
    workflow = loads_workflow_ir(args.workflow.read_text()) if args.workflow else None
    compiled = load_trace_dataset(args.compile) if args.compile else None
    if args.partition == "test" and (
        manifest.get("report_source_sha256")
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or (
            workflow is not None
            and (
                manifest.get("workflow_sha256")
                != digest(workflow.model_dump(mode="json"))
                or manifest.get("compile_sha256")
                != digest(compiled.model_dump(mode="json"))
            )
        )
    ):
        parser.error("test report generator/workflow/source must match pre-test freeze")
    contents = [
        (path, path.read_bytes()) for path in sorted(args.recordings.glob("*/raw.json"))
    ]
    records = [loads_json_document(raw.decode()) for _, raw in contents]
    report = build_report(plan, records, args.partition, workflow, compiled)
    report["report_source_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    report["raw_inventory"] = [
        {"case_id": path.parent.name, "raw_sha256": hashlib.sha256(raw).hexdigest()}
        for path, raw in contents
    ]
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "planned": report["agent"]["planned_cases"],
                "evaluated": report["agent"]["evaluated_cases"],
                "correct": report["agent"]["correct_cases"],
                "score_final": report["agent"]["score_final"],
            }
        )
    )
    return 0


def freeze_main(argv=None) -> int:
    """Pin report/review implementations and decisions before looking at test runs."""
    from datetime import datetime

    from .agent_contract_review import ContractReviewPlan
    from .agent_corpus import freeze

    parser = argparse.ArgumentParser(
        description="Freeze final workflow and empirical report contract"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--compile", required=True, type=Path)
    parser.add_argument("--review-plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--confirm-unseen-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_unseen_test:
        parser.error(
            "operator must explicitly confirm test results have not been inspected"
        )
    plan = load_plan(args.plan)
    workflow = loads_workflow_ir(args.workflow.read_text())
    compiled = load_trace_dataset(args.compile)
    decisions = ContractReviewPlan.model_validate(
        loads_json_document(args.review_plan.read_text())
    )
    expected = {case.case_id for case in plan.cases if case.partition == "compile"}
    included = {
        case_id
        for case_id, decision in decisions.cases.items()
        if decision.decision == "include"
    }
    if (
        set(decisions.cases) != expected
        or decisions.plan_sha256 != digest(plan.model_dump(mode="json"))
        or {run.inputs["task_id"] for run in compiled.runs} != included
        or len(compiled.runs) != len(included)
        or any(
            run.metadata.get("raw_sha256")
            != decisions.cases[run.inputs["task_id"]].raw_sha256
            for run in compiled.runs
        )
    ):
        parser.error(
            "final compile population must match all included decisions; keep exclusions in evaluation"
        )
    manifest = freeze(
        plan, args.output_dir, workflow=workflow, compile_dataset=compiled
    )
    manifest.update(
        report_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        contract_review_source_sha256=hashlib.sha256(
            Path(__file__).with_name("agent_contract_review.py").read_bytes()
        ).hexdigest(),
        review_plan_sha256=digest(decisions.model_dump(mode="json")),
        frozen_at_utc=datetime.now(UTC).isoformat(),
        reviewed_included_cases=sorted(included),
        reviewed_excluded_cases=sorted(expected - included),
        test_result_inspection_claim="not_inspected_by_operator_before_this_freeze; procedural_not_attestation",
    )
    with (args.output_dir / "report-freeze.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "workflow_sha256": manifest["workflow_sha256"],
                "report_source_sha256": manifest["report_source_sha256"],
                "included": len(included),
                "excluded": len(expected - included),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

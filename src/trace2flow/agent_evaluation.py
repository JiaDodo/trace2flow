"""Independent outcome checks with planned-task denominators and pending runs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from .agent_corpus import (
    CorpusPlan,
    assert_record_case,
    digest,
    load_plan,
    materialize,
    verify_freeze,
)
from .io import canonical_json, load_trace_dataset, loads_json_document
from .ir import WorkflowIR, loads_workflow_ir
from .simulation import CustomerSupportSimulator, execute_local


def evaluate_record(plan: CorpusPlan, record: dict) -> dict:
    case = assert_record_case(plan, record)
    oracle = materialize(case)["oracle"]
    updates = [
        call
        for call in record["calls"]
        if call["tool"] == "update_ticket" and call["status"] == "completed"
    ]
    write_attempted = any(call["tool"] == "update_ticket" for call in record["calls"])
    output = updates[-1]["output"] if updates else None
    state_match = digest(record["state_after"]) == digest(
        oracle["expected_state_after"]
    )
    output_match = digest(output) == digest(oracle["expected_final_output"])
    # Safety-only no-write is not proof that the model correctly communicated a refusal.
    correct = (
        record["ending"] == "model_finished"
        and state_match
        and output_match
        and (not write_attempted if oracle["action"] == "refuse" else bool(updates))
    )
    return {
        "case_id": case.case_id,
        "partition": case.partition,
        "expected_action": oracle["action"],
        "status": "evaluated",
        "ending": record["ending"],
        "correct": correct,
        "output_match": output_match,
        "complete_state_match": state_match,
        "write_attempted": write_attempted,
        "unsafe_write_attempt": oracle["action"] == "refuse" and write_attempted,
        "chat_claim_correctness_measured": False,
        "scripted_model": record["scripted_model"],
        "model_calls": record["model_calls"],
        "tool_calls": len(record["calls"]),
    }


def evaluate_inventory(plan: CorpusPlan, records: list[dict], partition: str) -> dict:
    """Require one run per planned case; repetitions need a predeclared trial inventory."""
    planned = {case.case_id for case in plan.cases if case.partition == partition}
    if not planned:
        raise ValueError("unknown or empty partition")
    results = {}
    for record in records:
        result = evaluate_record(plan, record)
        if result["case_id"] not in planned or result["case_id"] in results:
            raise ValueError("wrong partition or undeclared duplicate trial")
        results[result["case_id"]] = result
    return {
        "scope": "synthetic_local_business_outcomes",
        "partition": partition,
        "plan_sha256": digest(plan.model_dump(mode="json")),
        "planned_cases": len(planned),
        "evaluated_cases": len(results),
        "pending_cases": len(planned) - len(results),
        "correct_cases": sum(item["correct"] for item in results.values()),
        "unsafe_write_attempts": sum(
            item["unsafe_write_attempt"] for item in results.values()
        ),
        "score_final": len(planned) == len(results),
        "results": [
            results.get(case_id, {"case_id": case_id, "status": "not_run"})
            for case_id in sorted(planned)
        ],
    }


def evaluate_workflow(
    plan: CorpusPlan, workflow: WorkflowIR, partition: str, compile_dataset=None
) -> dict:
    """Declared preflight uses task/environment facts, never gold scenario labels."""
    if compile_dataset is None or compile_dataset.partition.value != "compile":
        raise ValueError("workflow evaluation requires its compile dataset")
    if workflow.source_dataset_id != compile_dataset.dataset_id:
        raise ValueError("workflow/compile source mismatch")
    if compile_dataset.metadata.get("plan_sha256") != digest(
        plan.model_dump(mode="json")
    ):
        raise ValueError("compile plan SHA mismatch")
    if (
        workflow.source_sha256
        != hashlib.sha256(canonical_json(compile_dataset).encode()).hexdigest()
    ):
        raise ValueError("workflow/compile content mismatch")
    compiled_groups = {run.provenance.task_group_id for run in compile_dataset.runs}
    if any(
        run.metadata.get("synthetic_environment") is not True
        or run.provenance.source != "trace2flow/customer-support-agent/v1"
        or run.provenance.task_group_id
        not in {case.group_id for case in plan.cases if case.partition == "compile"}
        for run in compile_dataset.runs
    ):
        raise ValueError("compile data is not bound to this corpus plan")
    by_case = {case.case_id: case for case in plan.cases if case.partition == "compile"}
    for run in compile_dataset.runs:
        case = by_case.get(run.inputs.get("task_id"))
        if case is None:
            raise ValueError("compile run is not a planned compile case")
        payload = materialize(case)
        if (
            digest(run.inputs) != digest(payload["task"])
            or digest(run.state_before) != digest(payload["state_before"])
            or run.provenance.task_group_id != case.group_id
            or run.metadata.get("collection_context")
            != {
                "plan_sha256": digest(plan.model_dump(mode="json")),
                "case_sha256": digest(payload),
                "partition": "compile",
            }
        ):
            raise ValueError("compile run content does not match its planned case")
    cases = [case for case in plan.cases if case.partition == partition]
    if partition == "compile" or not cases:
        raise ValueError("workflow evaluation requires a non-compile partition")
    if any(case.group_id in compiled_groups for case in cases):
        raise ValueError("compile task group leaks into evaluation")
    results = []
    for case in cases:
        payload = materialize(case)
        state = copy.deepcopy(payload["state_before"])
        task = payload["task"]
        simulator = CustomerSupportSimulator(**state)
        registry = simulator.registry()
        # An explicit customer-support admission contract, not inferred branch synthesis.
        customer, order = task["customer_id"], task["order_id"]
        admitted = (
            customer in state["customers"]
            and order in state["orders"]
            and state["orders"][order]["customer_id"] == customer
            and not workflow.execution_blockers()
            and {node.tool for node in workflow.nodes} <= registry.names
        )
        output, error = None, None
        if admitted:
            try:
                output = execute_local(workflow, task, registry).final_output
            except Exception as exc:  # noqa: BLE001 - failures stay in the report; no exception text leakage
                error = type(exc).__name__
        oracle = payload["oracle"]
        actual_state = {
            "customers": simulator.customers,
            "orders": simulator.orders,
            "tickets": simulator.tickets,
        }
        state_match = digest(actual_state) == digest(oracle["expected_state_after"])
        output_match = digest(output) == digest(oracle["expected_final_output"])
        correct = (
            error is None
            and state_match
            and output_match
            and admitted == (oracle["action"] == "execute")
        )
        results.append(
            {
                "case_id": case.case_id,
                "admitted": admitted,
                "correct": correct,
                "output_match": output_match,
                "complete_state_match": state_match,
                "unsafe_acceptance": admitted and oracle["action"] == "refuse",
                "error": error,
            }
        )
    accepted = sum(item["admitted"] for item in results)
    accepted_correct = sum(item["admitted"] and item["correct"] for item in results)
    return {
        "scope": "independent_synthetic_local_execution",
        "partition": partition,
        "admission_policy": "declared_customer_order_identity_contract_not_mined_branch",
        "planned_cases": len(cases),
        "accepted_cases": accepted,
        "coverage": accepted / len(cases),
        "accepted_correct_cases": accepted_correct,
        "accepted_case_correctness": accepted_correct / accepted if accepted else None,
        "unsafe_acceptances": sum(item["unsafe_acceptance"] for item in results),
        "correct_cases": sum(item["correct"] for item in results),
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate every planned case without dropping missing runs"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("recordings", type=Path)
    parser.add_argument(
        "--partition", choices=["compile", "development", "test"], required=True
    )
    parser.add_argument("--unlock-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--compile", type=Path)
    args = parser.parse_args(argv)
    if args.partition == "test" and not args.unlock_test:
        parser.error(
            "test evaluation requires --unlock-test; freeze implementation before using it"
        )
    plan = load_plan(args.plan)
    if args.partition == "test" and args.manifest is None:
        parser.error("test evaluation requires a source-pinned --manifest")
    if args.manifest:
        verify_freeze(plan, loads_json_document(args.manifest.read_text()))
    records = [
        loads_json_document(path.read_text())
        for path in sorted(args.recordings.glob("*/raw.json"))
    ]
    report = {"agent": evaluate_inventory(plan, records, args.partition)}
    if args.workflow:
        if args.compile is None:
            parser.error("workflow evaluation needs --compile")
        workflow = loads_workflow_ir(args.workflow.read_text())
        compile_dataset = load_trace_dataset(args.compile)
        if args.partition == "test":
            manifest = loads_json_document(args.manifest.read_text())
            if manifest.get("workflow_sha256") != digest(
                workflow.model_dump(mode="json")
            ) or manifest.get("compile_sha256") != digest(
                compile_dataset.model_dump(mode="json")
            ):
                parser.error(
                    "test workflow/source must match artifacts frozen before test collection"
                )
        report["workflow"] = evaluate_workflow(
            plan, workflow, args.partition, compile_dataset
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Predeclared paired evaluation for the standard Agent and M13b router."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .io import loads_json_document
from .models import StrictModel, json_compatible
from .support_agent import CustomerSupportAgent, SupportRequest, deepseek_support_model
from .support_backend import SupportBackend
from .support_reference import reference_delivery_registration
from .support_router import AdaptiveSupportRouter, WorkflowRegistry


class ExpectedTicket(StrictModel):
    status: Literal["pending_carrier", "replacement_offered", "pending_review"] | None
    category: Literal["delivery_delay", "damaged_item", "billing_duplicate"] | None

    @model_validator(mode="after")
    def paired(self):
        if (self.status is None) != (self.category is None):
            raise ValueError("expected status and category must both be set or both be null")
        return self


class PairedCase(StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    task_group_id: str
    customer_id: str
    ticket_id: str
    message: str
    expected_ticket: ExpectedTicket
    expected_router_route: Literal["workflow", "agent"]
    expected_answer_any: list[str] = Field(min_length=1)


class PairedPlan(StrictModel):
    schema_version: Literal["support-paired-plan/1.0"]
    plan_id: str
    model: str
    environment: Literal["synthetic_local_support_backend"]
    attempts_per_case_per_arm: Literal[1]
    arms: list[Literal["agent", "adaptive"]]
    approval_policy: Literal["approve_only_exact_expected_proposal"]
    compile_task_group_ids: list[str]
    metrics: list[str]
    cases: list[PairedCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self):
        if self.arms != ["agent", "adaptive"]:
            raise ValueError("paired arms must be agent then adaptive")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        evaluation_groups = {case.task_group_id for case in self.cases}
        overlap = evaluation_groups.intersection(self.compile_task_group_ids)
        if overlap:
            raise ValueError(
                "compile and evaluation task groups overlap: "
                + ", ".join(sorted(overlap))
            )
        return self


def _wilson_95(successes: int, total: int) -> list[float]:
    """Return a Wilson interval without pretending the tiny set is representative."""
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return [centre - margin, centre + margin]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(path: Path) -> PairedPlan:
    return PairedPlan.model_validate(loads_json_document(path.read_text(encoding="utf-8")))


def create_freeze(plan_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    root = Path(__file__).resolve().parents[2]
    plan = load_plan(plan_path)
    registration = reference_delivery_registration()
    sources = {
        name: _sha(root / name)
        for name in (
            "src/trace2flow/support_agent.py",
            "src/trace2flow/support_backend.py",
            "src/trace2flow/support_router.py",
            "src/trace2flow/support_reference.py",
            "src/trace2flow/support_evaluation.py",
        )
    }
    payload = {
        "schema_version": "support-paired-freeze/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": _sha(plan_path),
        "source_sha256": sources,
        "workflow_sha256": registration.workflow_sha256,
        "registration": registration.model_dump(mode="json"),
        "frozen_before_results": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def verify_freeze(plan_path: Path, freeze_path: Path) -> tuple[PairedPlan, dict]:
    root = Path(__file__).resolve().parents[2]
    plan = load_plan(plan_path)
    freeze = loads_json_document(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("plan_id") != plan.plan_id or freeze.get("plan_sha256") != _sha(plan_path):
        raise ValueError("evaluation plan differs from the frozen plan")
    for name, expected in freeze.get("source_sha256", {}).items():
        if _sha(root / name) != expected:
            raise ValueError(f"frozen evaluation source changed: {name}")
    registration = reference_delivery_registration()
    if registration.workflow_sha256 != freeze.get("workflow_sha256"):
        raise ValueError("reference workflow differs from frozen workflow")
    if registration.model_dump(mode="json") != freeze.get("registration"):
        raise ValueError("reference registration differs from frozen registration")
    return plan, freeze


def _proposal(turn) -> tuple[str | None, str | None]:
    if turn.status != "approval_required" or not turn.pending_actions:
        return None, None
    action = turn.pending_actions[0]
    if action.get("name") == "execute_registered_workflow":
        return "pending_carrier", "delivery_delay"
    args = action.get("args", {})
    return args.get("status"), args.get("category")


def _usage_and_calls(turn) -> tuple[int, int, int, int, int]:
    trace = turn.trace
    if turn.route == "agent":
        trace = trace["agent_trace"]
        calls = trace.get("calls", [])
        events = trace.get("events", [])
        model_calls = trace.get("model_calls", 0)
    else:
        calls = trace.get("execution_calls", trace.get("preview_calls", []))
        events = []
        model_calls = 0
    input_tokens = sum(
        (event.get("usage") or {}).get("input_tokens", 0)
        for event in events
        if event.get("role") == "assistant"
    )
    output_tokens = sum(
        (event.get("usage") or {}).get("output_tokens", 0)
        for event in events
        if event.get("role") == "assistant"
    )
    failures = sum(call.get("status") == "failed" for call in calls)
    return model_calls, len(calls), input_tokens, output_tokens, failures


def _state_correct(before: dict, after: dict, case: PairedCase) -> bool:
    expected = case.expected_ticket
    if expected.status is None:
        return after == before
    if any(after[key] != before[key] for key in ("customers", "orders", "shipping", "payments", "runtime")):
        return False
    for ticket_id, ticket in after["tickets"].items():
        original = before["tickets"][ticket_id]
        if ticket_id != case.ticket_id and ticket != original:
            return False
    ticket = after["tickets"][case.ticket_id]
    if not (
        ticket["status"] == expected.status
        and ticket["category"] == expected.category
        and ticket["revision"] == before["tickets"][case.ticket_id]["revision"] + 1
        and isinstance(ticket["summary"], str)
        and bool(ticket["summary"].strip())
    ):
        return False
    return len(after["applied_writes"]) == 1


def _output_correct(answer: str | None, case: PairedCase) -> bool:
    if not answer or not any(term in answer for term in case.expected_answer_any):
        return False
    false_external_actions = ("已经退款", "已退款", "已联系承运商", "已经联系承运商")
    return not any(phrase in answer for phrase in false_external_actions)


def _adaptive_turn(router, request, expected: ExpectedTicket):
    turn = router.invoke(request)
    proposed = _proposal(turn)
    expected_pair = (expected.status, expected.category)
    proposal_correct = proposed == expected_pair
    unsafe_proposal = turn.status == "approval_required" and not proposal_correct
    if turn.status == "approval_required":
        decision = "approve" if proposal_correct else "reject"
        turn = router.resume(request.thread_id, decision)
    return turn, proposed, proposal_correct, unsafe_proposal


def run_evaluation(plan_path: Path, freeze_path: Path, output_dir: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    plan, freeze = verify_freeze(plan_path, freeze_path)
    output_dir.mkdir(parents=True)
    attempts = []
    registration = reference_delivery_registration()
    for case in plan.cases:
        for arm in plan.arms:
            backend = SupportBackend.demo()
            before = backend.snapshot()
            model = deepseek_support_model(plan.model)
            agent = CustomerSupportAgent(model, backend, model_id=plan.model)
            if arm == "adaptive":
                registry = WorkflowRegistry()
                registry.register(registration)
                app = AdaptiveSupportRouter(agent=agent, backend=backend, registry=registry)
            else:
                # A zero-registration router gives both arms the same public API.
                app = AdaptiveSupportRouter(agent=agent, backend=backend, registry=WorkflowRegistry())
            request = SupportRequest(
                thread_id=f"{plan.plan_id}-{case.case_id}-{arm}",
                ticket_id=case.ticket_id,
                authenticated_customer_id=case.customer_id,
                message=case.message,
            )
            started = time.monotonic()
            try:
                turn, proposed, proposal_correct, unsafe_proposal = _adaptive_turn(
                    app, request, case.expected_ticket
                )
                runner_error_type = None
            except Exception as exc:  # noqa: BLE001 - retain type, never provider text
                turn = None
                proposed = (None, None)
                proposal_correct = proposed == (
                    case.expected_ticket.status,
                    case.expected_ticket.category,
                )
                unsafe_proposal = False
                runner_error_type = type(exc).__name__
            elapsed = time.monotonic() - started
            after = backend.snapshot()
            if turn is None:
                route = "agent" if arm == "agent" else "unknown"
                status = "error"
                model_calls = tool_calls = input_tokens = output_tokens = failures = 0
                route_correct = False
                answer = None
                turn_payload = None
            else:
                route = turn.route
                status = turn.status
                model_calls, tool_calls, input_tokens, output_tokens, failures = (
                    _usage_and_calls(turn)
                )
                route_correct = arm == "agent" or route == case.expected_router_route
                answer = turn.answer
                turn_payload = turn.model_dump(mode="json")
            state_correct = _state_correct(before, after, case)
            output_correct = _output_correct(answer, case)
            unsafe_write = unsafe_proposal and after != before
            record = {
                "schema_version": "support-paired-attempt/1.0",
                "case_id": case.case_id,
                "task_group_id": case.task_group_id,
                "arm": arm,
                "route": route,
                "route_correct": route_correct,
                "status": status,
                "runner_error_type": runner_error_type,
                "proposed": {"status": proposed[0], "category": proposed[1]},
                "proposal_correct": proposal_correct,
                "unsafe_proposal": unsafe_proposal,
                "unsafe_write": unsafe_write,
                "state_correct": state_correct,
                "output_correct": output_correct,
                "outcome_correct": (
                    state_correct and output_correct and status == "completed"
                ),
                "model_calls": model_calls,
                "tool_calls": tool_calls,
                "tool_failures": failures,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_reported": model_calls == 0 or input_tokens + output_tokens > 0,
                "elapsed_seconds": elapsed,
                "turn": turn_payload,
                "state_before": before,
                "state_after": after,
            }
            attempt_path = output_dir / f"{case.case_id}-{arm}.json"
            with attempt_path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(json_compatible(record), ensure_ascii=False, indent=2) + "\n")
            attempts.append(record)
    report = _report(plan, freeze_path, freeze, attempts)
    with (output_dir / "report.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(json_compatible(report), ensure_ascii=False, indent=2) + "\n")
    return report


def _report(plan: PairedPlan, freeze_path: Path, freeze: dict, attempts: list[dict]) -> dict:
    arms = {}
    for arm in plan.arms:
        rows = [row for row in attempts if row["arm"] == arm]
        arms[arm] = {
            "attempts": len(rows),
            "outcome_correct": sum(row["outcome_correct"] for row in rows),
            "state_correct": sum(row["state_correct"] for row in rows),
            "output_correct": sum(row["output_correct"] for row in rows),
            "proposal_correct": sum(row["proposal_correct"] for row in rows),
            "unsafe_proposals": sum(row["unsafe_proposal"] for row in rows),
            "unsafe_writes": sum(row["unsafe_write"] for row in rows),
            "errors": sum(row["status"] == "error" for row in rows),
            "workflow_routes": sum(row["route"] == "workflow" for row in rows),
            "agent_fallbacks": sum(row["route"] == "agent" for row in rows),
            "correct_routes": sum(row["route_correct"] for row in rows),
            "model_calls": sum(row["model_calls"] for row in rows),
            "tool_calls": sum(row["tool_calls"] for row in rows),
            "tool_failures": sum(row["tool_failures"] for row in rows),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "elapsed_seconds": sum(row["elapsed_seconds"] for row in rows),
        }
        for field in ("outcome_correct", "state_correct", "output_correct"):
            arms[arm][f"{field}_rate"] = arms[arm][field] / len(rows)
            arms[arm][f"{field}_wilson_95"] = _wilson_95(
                arms[arm][field], len(rows)
            )
    baseline = arms["agent"]
    adaptive = arms["adaptive"]
    deltas = {
        "outcome_correct_rate": (
            adaptive["outcome_correct_rate"] - baseline["outcome_correct_rate"]
        ),
        "state_correct_rate": (
            adaptive["state_correct_rate"] - baseline["state_correct_rate"]
        ),
        "output_correct_rate": (
            adaptive["output_correct_rate"] - baseline["output_correct_rate"]
        ),
        "model_calls": adaptive["model_calls"] - baseline["model_calls"],
        "tool_calls": adaptive["tool_calls"] - baseline["tool_calls"],
        "tool_failures": adaptive["tool_failures"] - baseline["tool_failures"],
        "total_tokens": (
            adaptive["input_tokens"]
            + adaptive["output_tokens"]
            - baseline["input_tokens"]
            - baseline["output_tokens"]
        ),
        "elapsed_seconds": adaptive["elapsed_seconds"] - baseline["elapsed_seconds"],
    }
    public_attempts = [
        {key: row[key] for key in (
            "case_id", "task_group_id", "arm", "route", "route_correct", "status",
            "proposal_correct", "unsafe_proposal", "unsafe_write", "state_correct",
            "output_correct", "outcome_correct", "model_calls", "tool_calls",
            "tool_failures", "input_tokens", "output_tokens", "usage_reported",
            "elapsed_seconds", "runner_error_type",
        )}
        for row in attempts
    ]
    return {
        "schema_version": "support-paired-report/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": freeze["plan_sha256"],
        "freeze_sha256": _sha(freeze_path),
        "synthetic_business_evaluation": True,
        "contains_real_customer_data": False,
        "arms": arms,
        "adaptive_minus_agent": deltas,
        "adaptive_workflow_coverage": (
            adaptive["workflow_routes"] / adaptive["attempts"]
        ),
        "sample_size_warning": (
            "Six synthetic cases with one attempt per arm are integration evidence, "
            "not a production or population estimate."
        ),
        "attempts": public_attempts,
        "claims_excluded": [
            "production reliability", "general model accuracy", "real-customer impact",
            "cost savings without provider price calculation",
        ],
    }


def publish_report(private_report: Path, freeze_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    report = loads_json_document(private_report.read_text(encoding="utf-8"))
    if report.get("schema_version") != "support-paired-report/1.0":
        raise ValueError("unsupported paired report schema")
    if report.get("freeze_sha256") != _sha(freeze_path):
        raise ValueError("paired report does not match the frozen evaluation")
    forbidden = {"turn", "state_before", "state_after", "message", "answer"}
    if forbidden.intersection(json.dumps(report, ensure_ascii=False).split('"')):
        raise ValueError("public report contains private attempt fields")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M13c paired support evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("plan", type=Path)
    freeze.add_argument("output", type=Path)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("plan", type=Path)
    evaluate.add_argument("freeze", type=Path)
    evaluate.add_argument("output", type=Path)
    evaluate.add_argument("--allow-paid-call", action="store_true")
    evaluate.add_argument("--unlock-evaluation", action="store_true")
    publish = sub.add_parser("publish")
    publish.add_argument("private_report", type=Path)
    publish.add_argument("freeze", type=Path)
    publish.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = create_freeze(args.plan, args.output)
    elif args.command == "evaluate":
        if not args.allow_paid_call or not args.unlock_evaluation:
            parser.error("evaluation requires --allow-paid-call and --unlock-evaluation")
        result = run_evaluation(args.plan, args.freeze, args.output)
    else:
        result = publish_report(args.private_report, args.freeze, args.output)
    print(json.dumps(json_compatible(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

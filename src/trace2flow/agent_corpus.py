"""Predeclared synthetic tasks, isolated environments and independent oracles."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .agent_collect import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    AgentTask,
    Collector,
    deepseek_model,
    run_agent,
    save_recording,
)
from .io import canonical_json, loads_json_document
from .models import StrictModel
from .simulation import CustomerSupportSimulator

Role = Literal["compile", "development", "test"]
FROZEN_SOURCES = (
    "agent_corpus.py",
    "agent_collect.py",
    "agent_review.py",
    "agent_evaluation.py",
    "agent_build.py",
    "candidate.py",
    "ir.py",
    "runtime.py",
    "simulation.py",
)
Scenario = Literal[
    "delivery_delay",
    "damaged_item",
    "billing_duplicate",
    "general_review",
    "foreign_order",
    "missing_order",
    "unknown_customer",
    "missing_customer",
]

# Explicit business expectations, not calls to the implementation being tested.
EXPECTED = {
    "delivery_delay": ("carrier_investigation", "pending_carrier"),
    "damaged_item": ("replacement_offer", "replacement_offered"),
    "billing_duplicate": ("manual_refund_review", "pending_review"),
    "general_review": ("human_review", "pending_review"),
}


class CaseSpec(StrictModel):
    case_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    group_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    partition: Role
    scenario: Scenario
    ticket_text: str = Field(min_length=1)


class CorpusPlan(StrictModel):
    schema_version: Literal["agent-corpus-plan/1.0"]
    corpus_id: str
    cases: list[CaseSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partitions(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case ID")
        groups = {}
        group_scenarios = {}
        for case in self.cases:
            if case.group_id in groups and groups[case.group_id] != case.partition:
                raise ValueError("task group crosses partitions")
            groups[case.group_id] = case.partition
            if (
                case.group_id in group_scenarios
                and group_scenarios[case.group_id] != case.scenario
            ):
                raise ValueError(
                    "one task group cannot contain different business scenarios"
                )
            group_scenarios[case.group_id] = case.scenario
        if {case.partition for case in self.cases} != {
            "compile",
            "development",
            "test",
        }:
            raise ValueError("all three partitions are required")
        entities = {}
        for case in self.cases:
            payload = materialize(case)
            identities = {
                kind: set(objects) for kind, objects in payload["state_before"].items()
            }
            for kind, field in (
                ("customers", "customer_id"),
                ("orders", "order_id"),
                ("tickets", "ticket_id"),
            ):
                if payload["task"][field] is not None:
                    identities[kind].add(payload["task"][field])
            for kind, objects in identities.items():
                for entity_id in objects:
                    key = (kind, entity_id)
                    if key in entities and entities[key] != case.partition:
                        raise ValueError("entity identity crosses partitions")
                    entities[key] = case.partition
        return self


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def load_plan(path: Path) -> CorpusPlan:
    return CorpusPlan.model_validate(
        loads_json_document(path.read_text(encoding="utf-8"))
    )


def materialize(case: CaseSpec) -> dict:
    """A case's entities depend on its group, so paraphrases cannot leak entities."""
    prefix = case.group_id
    customer_id, other_customer = "C-" + prefix, "C-other-" + prefix
    order_id, ticket_id = "O-" + prefix, "T-" + case.case_id
    order = {
        "order_id": order_id,
        "customer_id": customer_id,
        "status": "delivered",
        "delivered": True,
        "damaged": False,
        "duplicate_charge": False,
    }
    if case.scenario == "delivery_delay":
        order.update(status="shipped", delivered=False)
    elif case.scenario == "damaged_item":
        order["damaged"] = True
    elif case.scenario == "billing_duplicate":
        order["duplicate_charge"] = True
    elif case.scenario == "foreign_order":
        order["customer_id"] = other_customer
    state = {
        "customers": {
            customer_id: {"customer_id": customer_id},
            other_customer: {"customer_id": other_customer},
        },
        "orders": {order_id: order},
        "tickets": {
            ticket_id: {"ticket_id": ticket_id, "status": "open"},
            "T-unrelated-" + prefix: {
                "ticket_id": "T-unrelated-" + prefix,
                "status": "open",
            },
        },
    }
    supplied_order = None if case.scenario == "missing_order" else order_id
    supplied_customer = None if case.scenario == "missing_customer" else customer_id
    if case.scenario == "unknown_customer":
        supplied_customer = "C-unknown-" + prefix
    task = AgentTask(
        task_id=case.case_id,
        customer_id=supplied_customer,
        order_id=supplied_order,
        ticket_id=ticket_id,
        ticket_text=case.ticket_text,
    )
    expected_state = copy.deepcopy(state)
    output = None
    if case.scenario in EXPECTED:
        recommendation, status = EXPECTED[case.scenario]
        output = {
            "ticket_id": ticket_id,
            "issue_type": case.scenario,
            "recommendation": recommendation,
            "status": status,
        }
        expected_state["tickets"][ticket_id] = copy.deepcopy(output)
    return {
        "spec": case.model_dump(mode="json"),
        "task": task.model_dump(mode="json"),
        "state_before": state,
        "oracle": {
            "action": "execute" if output else "refuse",
            "expected_final_output": output,
            "expected_state_after": expected_state,
        },
    }


def make_collector(
    plan: CorpusPlan, case: CaseSpec, *, model_id: str, scripted=False
) -> Collector:
    if case not in plan.cases:
        raise ValueError("case is not in plan")
    payload = materialize(case)
    state = payload["state_before"]
    simulator = CustomerSupportSimulator(
        customers=copy.deepcopy(state["customers"]),
        orders=copy.deepcopy(state["orders"]),
        tickets=copy.deepcopy(state["tickets"]),
    )
    return Collector(
        AgentTask.model_validate(payload["task"]),
        model_id=model_id,
        scripted=scripted,
        allow_read_batches=True,
        simulator=simulator,
        task_group_id=case.group_id,
        collection_context={
            "plan_sha256": digest(plan.model_dump(mode="json")),
            "case_sha256": digest(payload),
            "partition": case.partition,
        },
    )


def assert_record_case(plan: CorpusPlan, record: dict) -> CaseSpec:
    matching = [
        case for case in plan.cases if case.case_id == record["task"]["task_id"]
    ]
    if len(matching) != 1:
        raise ValueError("recording task is not in plan")
    case = matching[0]
    payload = materialize(case)
    if (
        digest(record["task"]) != digest(payload["task"])
        or digest(record["state_before"]) != digest(payload["state_before"])
        or record.get("task_group_id") != case.group_id
        or record.get("collection_context")
        != {
            "plan_sha256": digest(plan.model_dump(mode="json")),
            "case_sha256": digest(payload),
            "partition": case.partition,
        }
    ):
        raise ValueError("recording does not match frozen task, state or partition")
    if record.get("schema_version") != "agent-recording/1.0":
        raise ValueError("unsupported recording schema")
    if (
        record.get("system_prompt") != SYSTEM_PROMPT
        or record.get("prompt_sha256")
        != hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        or record.get("producer_sha256")
        != hashlib.sha256(
            Path(__file__).with_name("agent_collect.py").read_bytes()
        ).hexdigest()
    ):
        raise ValueError(
            "recording prompt or producer does not match this implementation"
        )
    return case


def freeze(
    plan: CorpusPlan, directory: Path, *, workflow=None, compile_dataset=None
) -> dict:
    if (workflow is None) != (compile_dataset is None):
        raise ValueError("freeze a workflow with its compile source together")
    if workflow is not None and (
        workflow.source_dataset_id != compile_dataset.dataset_id
        or workflow.source_sha256
        != hashlib.sha256(canonical_json(compile_dataset).encode()).hexdigest()
        or compile_dataset.metadata.get("corpus_partition") != "compile"
        or compile_dataset.metadata.get("plan_sha256")
        != digest(plan.model_dump(mode="json"))
        or workflow.execution_blockers()
    ):
        raise ValueError(
            "final workflow is blocked or does not match its compile plan/source"
        )
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "agent-corpus-freeze/1.0",
        "plan_sha256": digest(plan.model_dump(mode="json")),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "source_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in FROZEN_SOURCES
        },
        "cases": [
            {
                "case_id": case.case_id,
                "group_id": case.group_id,
                "partition": case.partition,
                "sha256": digest(materialize(case)),
            }
            for case in plan.cases
        ],
        "test_seal": "logical_only_not_access_control",
        "collection_status": "not_checked_by_freeze",
        "workflow_sha256": digest(workflow.model_dump(mode="json"))
        if workflow
        else None,
        "compile_sha256": digest(compile_dataset.model_dump(mode="json"))
        if compile_dataset
        else None,
    }
    for name, value in (
        ("plan.json", plan.model_dump(mode="json")),
        ("manifest.json", manifest),
    ):
        with (directory / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return manifest


def verify_freeze(plan: CorpusPlan, manifest: dict) -> None:
    if (
        manifest.get("schema_version") != "agent-corpus-freeze/1.0"
        or manifest.get("plan_sha256") != digest(plan.model_dump(mode="json"))
        or manifest.get("prompt_sha256")
        != hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        or manifest.get("cases")
        != [
            {
                "case_id": case.case_id,
                "group_id": case.group_id,
                "partition": case.partition,
                "sha256": digest(materialize(case)),
            }
            for case in plan.cases
        ]
        or manifest.get("source_sha256")
        != {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in FROZEN_SOURCES
        }
    ):
        raise ValueError(
            "freeze manifest changed or implementation no longer matches; freeze a new version"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Freeze or select a predeclared synthetic Agent task"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--unlock-test", action="store_true")
    parser.add_argument("--collect-output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--compile", type=Path)
    parser.add_argument("--allow-paid-call", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    if (args.workflow is not None or args.compile is not None) and (
        not args.freeze or args.workflow is None or args.compile is None
    ):
        parser.error("artifact pinning requires --freeze, --workflow and --compile")
    if args.freeze and (args.case_id or args.collect_output):
        parser.error("freeze and collection/selection are separate operations")
    if args.collect_output and not args.case_id:
        parser.error("collection requires an explicit case ID")
    if args.freeze:
        from .io import load_trace_dataset
        from .ir import loads_workflow_ir

        print(
            json.dumps(
                freeze(
                    plan,
                    args.freeze,
                    workflow=loads_workflow_ir(args.workflow.read_text())
                    if args.workflow
                    else None,
                    compile_dataset=load_trace_dataset(args.compile)
                    if args.compile
                    else None,
                ),
                indent=2,
            )
        )
    elif args.case_id:
        matches = [case for case in plan.cases if case.case_id == args.case_id]
        if not matches:
            parser.error("unknown case ID")
        case = matches[0]
        if case.partition == "test" and not args.unlock_test:
            parser.error(
                "test task selection requires --unlock-test; freeze implementation first"
            )
        if args.collect_output:
            if not args.allow_paid_call or not os.environ.get("DEEPSEEK_API_KEY"):
                parser.error(
                    "collection needs --allow-paid-call and configured DEEPSEEK_API_KEY"
                )
            if args.collect_output.exists() or args.manifest is None:
                parser.error("collection requires a new directory and --manifest")
            verify_freeze(plan, loads_json_document(args.manifest.read_text()))
            instance = make_collector(plan, case, model_id=args.model)
            run_agent(instance, deepseek_model(args.model))
            save_recording(instance, args.collect_output)
            print(
                json.dumps(
                    {
                        "ending": instance.ending,
                        "model_calls": instance.model_calls,
                        "tool_calls": len(instance.calls),
                    }
                )
            )
            return 0 if instance.ending == "model_finished" else 1
        else:
            # Agent-visible task only: never emit state or expected answers here.
            print(canonical_json(AgentTask.model_validate(materialize(case)["task"])))
    else:
        print(
            json.dumps(
                {
                    role: sum(case.partition == role for case in plan.cases)
                    for role in ("compile", "development", "test")
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

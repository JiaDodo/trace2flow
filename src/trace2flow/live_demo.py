"""Offline presentation of frozen evidence; never starts a model collector.

Public recording projections are lossy, not normalized traces or full provider
messages. Their original hashes identify private files, not model authenticity.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from .agent_collect import AgentTask
from .agent_corpus import CorpusPlan, digest, load_plan, materialize, verify_freeze
from .candidate import CandidateDag
from .demo import CUSTOMER_SUPPORT_TOOLS, PROJECT_ROOT
from .io import canonical_json, load_trace_dataset
from .ir import WorkflowIR, loads_workflow_ir
from .models import StrictModel, TraceDataset
from .prefect_export import export_prefect
from .simulation import CustomerSupportSimulator, execute_local, state_diff

ARCHIVE = PROJECT_ROOT / "examples/customer-support-agent/live-v1"
PLAN = PROJECT_ROOT / "examples/customer-support-agent/corpus-plan.json"
SHOWCASE_CASES = ("compile-01", "test-01", "compile-10", "test-11")


class ProjectedCall(StrictModel):
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    params: dict[str, JsonValue]
    output: JsonValue
    status: Literal["completed", "failed"]
    error_type: str | None


class RecordingProjection(StrictModel):
    schema_version: Literal["agent-recording-projection/1.0"]
    projection_kind: Literal["lossy_task_and_tool_facts_without_model_messages"]
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str
    partition: Literal["compile", "development", "test"]
    run_id: str
    task: AgentTask
    environment: Literal["synthetic_local_simulator"]
    contains_real_customer_data: Literal[False]
    scripted_model: Literal[False]
    model_requested: str
    model_snapshot_pinned: bool
    model_calls: int = Field(ge=0)
    ending: str
    calls: list[ProjectedCall]


@dataclass(frozen=True)
class LiveDemoArchive:
    plan: CorpusPlan
    compile_dataset: TraceDataset
    candidate: CandidateDag
    workflow: WorkflowIR
    reports: dict[str, dict]
    recordings: dict[str, RecordingProjection]
    prefect_source: str


def load_live_demo(
    archive: Path = ARCHIVE, plan_path: Path = PLAN
) -> LiveDemoArchive:
    """Load public files only; reject stale/mixed artifacts before showing scores."""
    index = json.loads((archive / "demo-index.json").read_text(encoding="utf-8"))
    required = {
        "final-freeze.json", "review-plan.json", "compile-report.json",
        "development-report.json", "test-report.json", "artifacts/compile.json",
        "artifacts/candidate.json", "artifacts/workflow.json",
        "artifacts/prefect_flow.py",
        *(f"recordings/{case}.json" for case in SHOWCASE_CASES),
    }
    if index.get("schema_version") != "live-demo-index/1.0" or set(
        index.get("files", {})
    ) != required:
        raise ValueError("unexpected demo file inventory")
    for relative in sorted(required):
        actual = hashlib.sha256((archive / relative).read_bytes()).hexdigest()
        if actual != index["files"][relative]:
            raise ValueError(f"demo archive checksum mismatch: {relative}")
    plan = load_plan(plan_path)
    freeze = json.loads((archive / "final-freeze.json").read_text())
    verify_freeze(plan, freeze)
    if digest(plan.model_dump(mode="json")) != freeze["plan_sha256"]:
        raise ValueError("demo plan differs from frozen plan")
    data = load_trace_dataset(archive / "artifacts/compile.json")
    workflow = loads_workflow_ir((archive / "artifacts/workflow.json").read_text())
    candidate = CandidateDag.model_validate_json(
        (archive / "artifacts/candidate.json").read_text()
    )
    source_sha = hashlib.sha256(canonical_json(data).encode()).hexdigest()
    if (
        digest(data.model_dump(mode="json")) != freeze["compile_sha256"]
        or digest(workflow.model_dump(mode="json")) != freeze["workflow_sha256"]
        or workflow.source_sha256 != source_sha
        or candidate.source_sha256 != source_sha
    ):
        raise ValueError("demo artifacts differ from frozen content")
    prefect = (archive / "artifacts/prefect_flow.py").read_text()
    if prefect != export_prefect(workflow, CUSTOMER_SUPPORT_TOOLS).source:
        raise ValueError("demo Prefect source differs from safe export")
    reports = {}
    for role in ("compile", "development", "test"):
        report = json.loads((archive / f"{role}-report.json").read_text())
        expected = {case.case_id for case in plan.cases if case.partition == role}
        inventory = report["raw_inventory"]
        if (
            report["partition"] != role
            or report["plan_sha256"] != freeze["plan_sha256"]
            or {item["case_id"] for item in inventory} != expected
            or len(inventory) != len(expected)
            or report["agent"]["planned_cases"] != len(expected)
            or report["agent"]["pending_cases"] != 0
            or report["agent"]["score_final"] is not True
        ):
            raise ValueError("demo report inventory/plan mismatch")
        if role != "compile" and any(
            report[key] != freeze[key]
            for key in ("compile_sha256", "workflow_sha256", "report_source_sha256")
        ):
            raise ValueError("demo report differs from frozen workflow/scorer")
        reports[role] = report
    recordings = {}
    for case_id in SHOWCASE_CASES:
        projection = RecordingProjection.model_validate_json(
            (archive / f"recordings/{case_id}.json").read_text()
        )
        case = next(case for case in plan.cases if case.case_id == case_id)
        report = reports[case.partition]
        raw_hash = next(
            item["raw_sha256"] for item in report["raw_inventory"]
            if item["case_id"] == case_id
        )
        usage = next(
            item for item in report["agent_usage"]["results"]
            if item["case_id"] == case_id
        )
        if (
            projection.case_id != case_id
            or projection.partition != case.partition
            or projection.raw_sha256 != raw_hash
            or digest(projection.task.model_dump(mode="json"))
            != digest(materialize(case)["task"])
            or projection.model_calls != usage["model_calls"]
            or len(projection.calls) != usage["tool_calls"]
            or sum(call.status == "failed" for call in projection.calls)
            != usage["failed_tool_calls"]
            or len({call.id for call in projection.calls}) != len(projection.calls)
            or {call.tool for call in projection.calls} - CUSTOMER_SUPPORT_TOOLS
        ):
            raise ValueError("demo recording projection does not match inventory")
        if case.partition == "compile" and case_id != "compile-10":
            run = next(run for run in data.runs if run.inputs["task_id"] == case_id)
            if (
                projection.run_id != run.id
                or projection.raw_sha256 != run.metadata["raw_sha256"]
                or [(call.id, call.tool, digest(call.params), digest(call.output))
                    for call in projection.calls]
                != [(step.id, step.tool, digest(step.params), digest(step.output))
                    for step in run.steps]
            ):
                raise ValueError("demo recording differs from compiled occurrences")
        recordings[case_id] = projection
    return LiveDemoArchive(plan, data, candidate, workflow, reports, recordings, prefect)


def binding_rows(workflow: WorkflowIR) -> list[dict]:
    tools = {node.id: node.tool for node in workflow.nodes}
    rows = []
    for node in workflow.nodes:
        for parameter, binding in node.parameters.items():
            source = binding.kind
            if binding.kind == "task_input":
                source = "task." + ".".join(map(str, binding.path))
            elif binding.kind == "tool_output":
                source = tools[binding.source_node_id] + "." + ".".join(
                    map(str, binding.path)
                )
            rows.append({
                "目标节点": node.id, "工具": node.tool, "参数": parameter,
                "绑定类别": binding.kind, "声明来源": source,
                "观测证据数": len(getattr(binding, "evidence", [])),
            })
    return rows


def failure_rows(archive: LiveDemoArchive) -> list[dict]:
    """Retain all failure/zero-call runs, independent of compilation admission."""
    rows = []
    for role, report in archive.reports.items():
        for item in report["agent_usage"]["results"]:
            if item["failed_tool_calls"] or item["tool_calls"] == 0:
                rows.append({
                    "任务": item["case_id"], "分区": role,
                    "模型请求": item["model_calls"], "工具调用": item["tool_calls"],
                    "失败工具调用": item["failed_tool_calls"],
                    "证据": "零工具原始录制（未捏造规范化步骤）"
                    if item["tool_calls"] == 0 else "失败调用保留在原始清单",
                })
    return rows


def run_fresh_case(archive: LiveDemoArchive, case_id: str) -> dict:
    """Known regression on a new state, not response replay or a new holdout."""
    case = next((case for case in archive.plan.cases if case.case_id == case_id), None)
    if case is None or case.partition != "test":
        raise ValueError("select a known archived test case")
    payload = materialize(case)
    before = copy.deepcopy(payload["state_before"])
    simulator = CustomerSupportSimulator(**copy.deepcopy(before))
    registry = simulator.registry()
    task = payload["task"]
    customer, order = task["customer_id"], task["order_id"]
    # The same fixed explicit contract as M11; no scenario/oracle-based routing.
    reason = None
    if customer not in before["customers"]:
        reason = "客户编号缺失或客户不存在"
    elif order not in before["orders"]:
        reason = "订单不存在"
    elif before["orders"][order]["customer_id"] != customer:
        reason = "订单不属于任务客户"
    elif archive.workflow.execution_blockers():
        reason = "Workflow IR 存在未解决的执行阻塞"
    elif {node.tool for node in archive.workflow.nodes} - registry.names:
        reason = "工作流包含未注册工具"
    admitted = reason is None
    outputs, output, error = {}, None, None
    if admitted:
        try:
            execution = execute_local(archive.workflow, task, registry)
            outputs, output = execution.outputs, execution.final_output
        except Exception as exc:  # noqa: BLE001 - preserve failure, omit exception text
            error = type(exc).__name__
    after = copy.deepcopy({
        "customers": simulator.customers, "orders": simulator.orders,
        "tickets": simulator.tickets,
    })
    oracle = payload["oracle"]
    output_match = digest(output) == digest(oracle["expected_final_output"])
    state_match = digest(after) == digest(oracle["expected_state_after"])
    return {
        "scope": "known_archived_case_fresh_local_regression",
        "synthetic_environment": True, "recorded_response_replay_used": False,
        "model_calls": 0, "case_id": case_id, "task": task,
        "admitted": admitted, "refusal_reason": reason, "error": error,
        "outputs": outputs, "actual_final_output": output,
        "expected_final_output": oracle["expected_final_output"],
        "state_before": before, "actual_state_after": after,
        "expected_state_after": oracle["expected_state_after"],
        "actual_changes": [c.model_dump(mode="json") for c in state_diff(before, after)],
        "output_match": output_match, "complete_state_match": state_match,
        "correct": error is None and output_match and state_match
        and admitted == (oracle["action"] == "execute"),
    }

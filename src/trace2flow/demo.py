"""Pure helpers backing the Streamlit demo and its smoke tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .candidate import CandidateDag, candidate_json, mine_candidate_dag
from .io import loads_trace_dataset
from .ir import ResolutionPlan, WorkflowIR, build_workflow_ir, workflow_ir_json
from .prefect_export import PrefectArtifact, PrefectExportError, export_prefect
from .simulation import VerificationReport, verification_report_json, verify_workflow

CUSTOMER_SUPPORT_TOOLS = frozenset(
    {
        "lookup_customer",
        "lookup_order",
        "classify_issue",
        "recommend_action",
        "update_ticket",
    }
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = PROJECT_ROOT / "examples" / "customer-support"


@dataclass(frozen=True)
class DemoArtifacts:
    candidate: CandidateDag
    workflow: WorkflowIR
    prefect: PrefectArtifact | None
    verification: VerificationReport | None
    resolution_error: str | None = None
    export_error: str | None = None
    verification_error: str | None = None


def default_demo_texts() -> tuple[str, str, str]:
    return (
        (DEMO_ROOT / "compile.json").read_text(encoding="utf-8"),
        (DEMO_ROOT / "resolution.json").read_text(encoding="utf-8"),
        (DEMO_ROOT / "holdout.json").read_text(encoding="utf-8"),
    )


def build_demo_artifacts(
    compile_text: str,
    resolution_text: str,
    holdout_text: str | None = None,
    *,
    allow_unresolved_fallback: bool = False,
) -> DemoArtifacts:
    compile_dataset = loads_trace_dataset(compile_text)
    candidate = mine_candidate_dag(compile_dataset)
    resolution_error = None
    try:
        resolution = ResolutionPlan.model_validate_json(resolution_text)
        workflow = build_workflow_ir(compile_dataset, candidate, resolution)
    except (ValidationError, ValueError) as exc:
        if not allow_unresolved_fallback:
            raise
        resolution_error = f"{type(exc).__name__}: {exc}"
        workflow = build_workflow_ir(compile_dataset, candidate, ResolutionPlan())
    blockers = workflow.execution_blockers()
    export_error = None
    try:
        prefect = None if blockers else export_prefect(workflow, CUSTOMER_SUPPORT_TOOLS)
    except PrefectExportError as exc:
        if not allow_unresolved_fallback:
            raise
        prefect = None
        export_error = str(exc)
    verification = None
    verification_error = None
    if holdout_text is not None and not blockers:
        try:
            verification = verify_workflow(
                workflow,
                compile_dataset,
                loads_trace_dataset(holdout_text),
            )
        except ValueError as exc:
            if not allow_unresolved_fallback:
                raise
            verification_error = f"{type(exc).__name__}: {exc}"
    return DemoArtifacts(
        candidate=candidate,
        workflow=workflow,
        prefect=prefect,
        verification=verification,
        resolution_error=resolution_error,
        export_error=export_error,
        verification_error=verification_error,
    )


def candidate_dot(candidate: CandidateDag) -> str:
    lines = ["digraph trace2flow {", "rankdir=LR;", "node [shape=box];"]
    for node in candidate.nodes:
        color = "#dc2626" if node.alignment_status.value == "unresolved" else "#2563eb"
        label = f"{node.tool}\\n{node.alignment_status.value}"
        lines.append(
            f"{json.dumps(node.id)} [label={json.dumps(label)}, color={json.dumps(color)}];"
        )
    for edge in candidate.edges:
        label = f"{len(edge.supporting_evidence)} evidence"
        lines.append(
            f"{json.dumps(edge.source_node_id)} -> {json.dumps(edge.target_node_id)} "
            f"[label={json.dumps(label)}];"
        )
    for item in candidate.unresolved_dependencies:
        for direction in item.candidates:
            lines.append(
                f"{json.dumps(direction.source_node_id)} -> "
                f"{json.dumps(direction.target_node_id)} "
                f"[style=dashed, color=\"#dc2626\", label={json.dumps(item.reason)}];"
            )
    lines.append("}")
    return "\n".join(lines)


def evidence_rows(candidate: CandidateDag) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for edge in candidate.edges:
        for evidence in edge.supporting_evidence:
            rows.append(
                {
                    "status": "accepted",
                    "reason": "depends_on",
                    "source_node": edge.source_node_id,
                    "target_node": edge.target_node_id,
                    "run_id": evidence.run_id,
                    "source_occurrence": evidence.source_occurrence_id,
                    "target_occurrence": evidence.target_occurrence_id,
                }
            )
    for unresolved in candidate.unresolved_dependencies:
        for direction in unresolved.candidates:
            for evidence in direction.supporting_evidence:
                rows.append(
                    {
                        "status": "unresolved",
                        "reason": unresolved.reason,
                        "source_node": direction.source_node_id,
                        "target_node": direction.target_node_id,
                        "run_id": evidence.run_id,
                        "source_occurrence": evidence.source_occurrence_id,
                        "target_occurrence": evidence.target_occurrence_id,
                    }
                )
    return rows


def downloadable_json(artifacts: DemoArtifacts) -> dict[str, str]:
    result = {
        "candidate.json": candidate_json(artifacts.candidate),
        "workflow.json": workflow_ir_json(artifacts.workflow),
    }
    if artifacts.verification is not None:
        result["verification.json"] = verification_report_json(
            artifacts.verification
        )
    return result

"""Validate an explicitly reviewed, occurrence-ID-bound customer-support contract.

No tool-name/value matcher selects source occurrences. Review decisions supply
their exact IDs. This narrow contract rejects repeated/unsupported structures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from .agent_collect import SCHEMAS
from .agent_corpus import assert_record_case, digest, load_plan
from .agent_review import RecordingReview, draft_review, review_recording
from .io import loads_json_document
from .models import StrictModel

# Explicit future-execution contract, NOT discovery of the model's mental lineage.
INPUTS = {
    "lookup_customer": {"customer_id": "customer_id"},
    "lookup_order": {"order_id": "order_id", "customer_id": "customer_id"},
    "classify_issue": {"ticket_text": "ticket_text"},
    "recommend_action": {"policy_version": "policy_version"},
    "update_ticket": {"ticket_id": "ticket_id"},
}
OUTPUTS = {
    "classify_issue": {
        "order_status": ("lookup_order", "status"),
        "delivered": ("lookup_order", "delivered"),
        "damaged": ("lookup_order", "damaged"),
        "duplicate_charge": ("lookup_order", "duplicate_charge"),
    },
    "recommend_action": {
        "issue_type": ("classify_issue", "issue_type"),
        "eligible": ("classify_issue", "eligible"),
    },
    "update_ticket": {
        key: ("recommend_action", key)
        for key in ("issue_type", "recommendation", "status")
    },
}


class Decision(StrictModel):
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["include", "exclude_from_compilation"]
    rationale: str = Field(min_length=1)
    roles: dict[str, str] = Field(default_factory=dict)


class ContractReviewPlan(StrictModel):
    schema_version: Literal["agent-contract-review-plan/1.0"]
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1)
    reviewer_kind: Literal["ai"]
    redaction_confirmed: Literal[True]
    cases: dict[str, Decision]


def declaration(
    plan, raw_content: bytes, decision: Decision, reviewer: str
) -> RecordingReview:
    if hashlib.sha256(raw_content).hexdigest() != decision.raw_sha256:
        raise ValueError("decision raw SHA mismatch")
    record = loads_json_document(raw_content.decode())
    assert_record_case(plan, record)
    template = draft_review(plan, raw_content)
    template.update(
        reviewer=reviewer,
        redaction_confirmed=True,
        decision=decision.decision,
        rationale=decision.rationale,
    )
    if decision.decision == "exclude_from_compilation":
        if decision.roles:
            raise ValueError("exclusion does not assert executable source roles")
        for call in template["calls"].values():
            for binding in call["bindings"].values():
                binding["rationale"] = (
                    decision.rationale + "; no resolved lineage asserted"
                )
        return RecordingReview.model_validate(template)
    ids = [call["id"] for call in record["calls"]]
    if (
        set(decision.roles) != set(SCHEMAS)
        or len(ids) != 5
        or len(set(decision.roles.values())) != 5
        or set(decision.roles.values()) != set(ids)
    ):
        raise ValueError(
            "contract requires five explicitly reviewed distinct occurrence IDs"
        )
    by_id = {call["id"]: call for call in record["calls"]}
    for tool, call_id in decision.roles.items():
        if by_id[call_id]["tool"] != tool:
            raise ValueError("declared occurrence role contradicts its recorded tool")
        target = template["calls"][call_id]
        bindings, dependencies = {}, []
        for parameter, path in INPUTS[tool].items():
            bindings[parameter] = {
                "kind": "task_input",
                "path": [path],
                "rationale": "AI-reviewed explicit task-input execution contract; not value-inferred lineage",
            }
        for parameter, (source_role, path) in OUTPUTS.get(tool, {}).items():
            source_id = decision.roles[source_role]
            bindings[parameter] = {
                "kind": "tool_output",
                "source_call_id": source_id,
                "path": [path],
                "rationale": "AI-reviewed explicit source-field execution contract; not equality/chronology proof",
            }
            if source_id not in dependencies:
                dependencies.append(source_id)
        target.update(bindings=bindings, depends_on=dependencies)
    return RecordingReview.model_validate(template)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check an AI-reviewed explicit occurrence contract"
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    decisions = ContractReviewPlan.model_validate(
        loads_json_document(args.decisions.read_text())
    )
    expected = {case.case_id for case in plan.cases if case.partition == "compile"}
    paths = {path.parent.name: path for path in args.recordings.glob("*/raw.json")}
    if args.output_dir.exists():
        parser.error("output directory already exists; no overwrite")
    if set(decisions.cases) != expected or set(paths) != expected:
        parser.error(
            "all planned compile cases, including exclusions, must have records and decisions"
        )
    if decisions.plan_sha256 != digest(plan.model_dump(mode="json")):
        parser.error("decision plan SHA mismatch")
    prepared = []
    for case_id in sorted(expected):
        raw = paths[case_id].read_bytes()
        case = assert_record_case(plan, loads_json_document(raw.decode()))
        if case.partition != "compile":
            parser.error(
                "only compile recordings are reviewed by this contract entrypoint"
            )
        started = time.perf_counter()
        review = declaration(plan, raw, decisions.cases[case_id], decisions.reviewer)
        review_recording(plan, raw, review)
        # Only machine declaration/check wall time is measured. AI reasoning and
        # human effort are NOT fabricated as these milliseconds.
        review.review_minutes = (time.perf_counter() - started) / 60
        data = review_recording(plan, raw, review)
        if data is not None:
            data.metadata.update(
                reviewer_kind="ai",
                review_minutes_kind="automated_contract_check_wall_time",
                human_review_minutes=0,
                ai_reasoning_review_minutes=None,
                lineage_evidence="explicit_ai_reviewed_execution_contract",
                contract_sha256=digest({"inputs": INPUTS, "outputs": OUTPUTS}),
            )
            data.runs[0].metadata.update(
                reviewer_kind="ai",
                review_minutes_kind="automated_contract_check_wall_time",
            )
        prepared.append((case_id, review, data))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for case_id, review, data in prepared:
        directory = args.output_dir / case_id
        directory.mkdir()
        for name, value in (("review.json", review), ("reviewed.json", data)):
            if value is not None:
                with (directory / name).open("x", encoding="utf-8") as stream:
                    stream.write(value.model_dump_json(indent=2) + "\n")
    print(
        json.dumps(
            {
                "reviewer_kind": "ai",
                "included": sum(data is not None for _, _, data in prepared),
                "excluded": sum(data is None for _, _, data in prepared),
                "human_review_minutes": 0,
                "ai_reasoning_review_minutes": None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

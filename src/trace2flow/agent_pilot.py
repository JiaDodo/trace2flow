"""Fixed development-pilot checks, deliberately not a generic benchmark."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from .io import loads_json_document

PILOTS = {
    "m10-delivery-001": "stopped_read_batch",
    "m10-delivery-002": "stopped_read_batch",
    "m10-foreign-001": "stopped_read_batch",
    "m10-delivery-003": "delivery_delay",
    "m10-foreign-002": "foreign_order",
}


def check_development_record(record: dict, expectation: str) -> dict:
    """Expectations are independently fixed for the committed development tasks."""
    before, after = record["state_before"], record["state_after"]
    updates = [
        call
        for call in record["calls"]
        if call["tool"] == "update_ticket" and call["status"] == "completed"
    ]
    if expectation == "stopped_read_batch":
        output_match = not record["calls"]
        state_match = before == after
        ending_match = record["ending"] == "parallel_batch_requires_review"
    elif expectation == "delivery_delay":
        ticket_id = record["task"]["ticket_id"]
        expected_ticket = {
            "ticket_id": ticket_id,
            "status": "pending_carrier",
            "recommendation": "carrier_investigation",
            "issue_type": "delivery_delay",
        }
        expected_after = copy.deepcopy(before)
        expected_after["tickets"][ticket_id] = expected_ticket
        output_match = len(updates) == 1 and updates[0]["output"] == expected_ticket
        state_match = after == expected_after
        ending_match = record["ending"] == "model_finished"
    elif expectation == "foreign_order":
        output_match = not updates and any(
            call["tool"] == "lookup_order" and call["status"] == "failed"
            for call in record["calls"]
        )
        state_match = before == after
        ending_match = record["ending"] == "model_finished"
    else:
        raise ValueError("unknown development expectation")
    usage = [
        event["usage"]
        for event in record["events"]
        if event["role"] == "assistant" and event.get("usage") is not None
    ]
    return {
        "expectation": expectation,
        "ending": record["ending"],
        "passed": output_match and state_match and ending_match,
        "output_or_safe_refusal_match": output_match,
        "complete_state_match": state_match,
        "model_calls": record["model_calls"],
        "tool_calls": len(record["calls"]),
        "input_tokens": sum(item["input_tokens"] for item in usage),
        "output_tokens": sum(item["output_tokens"] for item in usage),
        "usage_events": len(usage),
        "chat_claim_correctness_measured": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the fixed M10 development pilot inventory"
    )
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    results = []
    for name, expectation in PILOTS.items():
        content = (args.root / name / "raw.json").read_bytes()
        result = check_development_record(
            loads_json_document(content.decode()), expectation
        )
        result.update(name=name, raw_sha256=hashlib.sha256(content).hexdigest())
        results.append(result)
    passed = all(result["passed"] for result in results)
    print(
        json.dumps(
            {
                "scope": "fixed_development_pilot_not_holdout",
                "passed": passed,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

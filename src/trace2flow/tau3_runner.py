"""Fail-closed runner and public summarizer for pinned τ³ retail batches.

The paid runner must be executed with the pinned τ³ checkout's Python
environment.  Imports of ``tau2`` are deliberately deferred so all plan,
manifest, and publication controls remain testable without that optional
external package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Identifier, StrictModel
from .tau3_corpus import (
    PINNED_TAU3_COMMIT,
    Tau3RetailManifest,
    audit_source,
)

REPORT_SCHEMA = "tau3-development-report/1.0"
AGENT_NAME = "trace2flow_single_call"
SAFE_RUN_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}\Z")


class Tau3RunError(ValueError):
    """The plan, runtime, or result inventory is unsafe or inconsistent."""


class Tau3SingleCallViolation(Tau3RunError):
    """The model proposed more than one assistant tool call in one turn."""


class PlannedTask(StrictModel):
    task_id: Identifier
    source_task_sha256: Identifier
    workflow_families: list[Identifier] = Field(min_length=1)


class Tau3DevelopmentPlan(StrictModel):
    schema_version: Literal[
        "tau3-development-plan/1.0", "tau3-development-plan/1.1"
    ]
    dataset: Literal["tau3-bench/retail"]
    source_commit: Identifier
    manifest_sha256: Identifier
    role: Literal["development"]
    tasks: list[PlannedTask] = Field(min_length=1)
    attempts_per_task: Literal[1]
    agent_implementation: Literal["trace2flow_single_call"]
    agent_model: Identifier
    user_model: Identifier
    evaluator_model: Identifier
    max_concurrency: int = Field(ge=1, le=4)
    max_steps: int = Field(ge=1, le=80)
    max_retries: Literal[0]
    hallucination_retries: Literal[0]
    seed: int = Field(ge=0)
    agent_prompt_contract: Literal["baseline", "strict_tool_only_response_v2"] = (
        "baseline"
    )
    runner_source_sha256: Identifier | None = None
    previously_attempted_task_ids: list[Identifier] = Field(default_factory=list)
    predecessor_report_sha256: Identifier | None = None
    test_gate_min_successful_results: int | None = Field(default=None, ge=1)
    test_gate_max_policy_violations: int | None = Field(default=None, ge=0)
    limitations: list[Identifier]

    @model_validator(mode="after")
    def unique_tasks(self) -> Tau3DevelopmentPlan:
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("development plan task ids must be unique")
        if set(ids) & set(self.previously_attempted_task_ids):
            raise ValueError("development tasks overlap previously attempted tasks")
        if self.schema_version == "tau3-development-plan/1.1":
            required = (
                self.runner_source_sha256,
                self.predecessor_report_sha256,
                self.test_gate_min_successful_results,
                self.test_gate_max_policy_violations,
            )
            if any(value is None for value in required):
                raise ValueError("version 1.1 requires source, predecessor, and test gate")
            if self.agent_prompt_contract != "strict_tool_only_response_v2":
                raise ValueError("version 1.1 requires the strict tool-only prompt")
        return self


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(path: Path) -> Tau3DevelopmentPlan:
    try:
        return Tau3DevelopmentPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Tau3RunError(f"invalid development plan: {type(exc).__name__}") from exc


def load_manifest(path: Path) -> Tau3RetailManifest:
    try:
        return Tau3RetailManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Tau3RunError(f"invalid corpus manifest: {type(exc).__name__}") from exc


def verify_plan(
    plan: Tau3DevelopmentPlan,
    manifest: Tau3RetailManifest,
    manifest_path: Path,
) -> None:
    if plan.source_commit != PINNED_TAU3_COMMIT:
        raise Tau3RunError("development plan source commit is not pinned")
    if plan.source_commit != manifest.source_commit:
        raise Tau3RunError("development plan and manifest source commits differ")
    if plan.manifest_sha256 != file_sha256(manifest_path):
        raise Tau3RunError("development plan manifest hash mismatch")
    if (
        plan.runner_source_sha256 is not None
        and plan.runner_source_sha256 != file_sha256(Path(__file__))
    ):
        raise Tau3RunError("development plan runner source hash mismatch")
    by_id = {task.task_id: task for task in manifest.train_tasks}
    for planned in plan.tasks:
        source = by_id.get(planned.task_id)
        if source is None:
            raise Tau3RunError(f"planned task is absent from train inventory: {planned.task_id}")
        if source.role != "development":
            raise Tau3RunError(f"planned task is not development-only: {planned.task_id}")
        if planned.source_task_sha256 != source.source_task_sha256:
            raise Tau3RunError(f"planned task hash mismatch: {planned.task_id}")
        if planned.workflow_families != source.workflow_families:
            raise Tau3RunError(f"planned task family mismatch: {planned.task_id}")


def require_paid_call(allow_paid_call: bool, environ: Mapping[str, str]) -> None:
    if not allow_paid_call:
        raise Tau3RunError("paid batch requires --allow-paid-call")
    if not environ.get("DEEPSEEK_API_KEY"):
        raise Tau3RunError("DEEPSEEK_API_KEY is unavailable")


def enforce_single_tool_call(message: Any) -> Any:
    """Fail the task instead of silently dropping or executing a tool batch."""

    calls = getattr(message, "tool_calls", None) or []
    assistant_calls = [
        call for call in calls if getattr(call, "requestor", "assistant") == "assistant"
    ]
    if len(assistant_calls) > 1:
        raise Tau3SingleCallViolation(
            "assistant proposed multiple tool calls in one turn"
        )
    return message


def _install_tau3_adapter(plan: Tau3DevelopmentPlan, source_root: Path):
    import tau2  # type: ignore[import-not-found]
    from tau2.agent.llm_agent import LLMAgent  # type: ignore[import-not-found]
    from tau2.registry import registry  # type: ignore[import-not-found]

    installed = Path(tau2.__file__).resolve()
    expected = (source_root / "src" / "tau2").resolve()
    if expected not in installed.parents:
        raise Tau3RunError("imported tau2 package is not from the pinned source root")

    class SingleCallAgent(LLMAgent):
        @property
        def system_prompt(self) -> str:
            prompt = (
                super().system_prompt
                + "\n\nYou must request at most one tool call in each assistant turn. "
                "Never batch or parallelize tool calls."
            )
            if plan.agent_prompt_contract == "strict_tool_only_response_v2":
                prompt += (
                    " When requesting a tool, return exactly one tool call and no "
                    "natural-language content: the assistant content field must be "
                    "null or empty. Do not explain the call. Wait for its result before "
                    "deciding the next action."
                )
            return prompt

        def _generate_next_message(self, message, state):
            return enforce_single_tool_call(super()._generate_next_message(message, state))

    def factory(tools, domain_policy, **kwargs):
        return SingleCallAgent(
            tools=tools,
            domain_policy=domain_policy,
            llm=kwargs.get("llm"),
            llm_args=kwargs.get("llm_args"),
        )

    if registry.get_agent_factory(AGENT_NAME) is not None:
        raise Tau3RunError("Trace2Flow τ³ agent is already registered")
    registry.register_agent_factory(factory, AGENT_NAME)

    from tau2.evaluator import evaluator_nl_assertions  # type: ignore[import-not-found]

    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = plan.evaluator_model
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = {"temperature": 0}
    return evaluator_nl_assertions


def _capture_evaluator_usage(evaluator_module):
    """Install a thread-local task label and aggregate evaluator token usage."""

    records: list[dict[str, Any]] = []
    lock = threading.Lock()
    current = threading.local()
    original_generate = evaluator_module.generate
    original_calculate = evaluator_module.NLAssertionsEvaluator.calculate_reward

    def generate_with_usage(*args, **kwargs):
        response = original_generate(*args, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            with lock:
                records.append(
                    {
                        "task_id": getattr(current, "task_id", None),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                    }
                )
        return response

    def calculate_with_task(task, full_trajectory):
        current.task_id = str(task.id)
        try:
            return original_calculate(task, full_trajectory)
        finally:
            current.task_id = None

    evaluator_module.generate = generate_with_usage
    evaluator_module.NLAssertionsEvaluator.calculate_reward = staticmethod(
        calculate_with_task
    )
    return records


def _write_private_metadata(path: Path, plan_path: Path, usage: list[dict]) -> None:
    payload = {
        "schema_version": "tau3-private-run-metadata/1.0",
        "plan_sha256": file_sha256(plan_path),
        "evaluator_usage": usage,
        "evaluator_usage_complete": all(
            item.get("prompt_tokens") is not None
            and item.get("completion_tokens") is not None
            for item in usage
        ),
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def run_paid_batch(
    plan_path: Path,
    manifest_path: Path,
    source_root: Path,
    save_to: str,
    *,
    allow_paid_call: bool,
) -> Path:
    require_paid_call(allow_paid_call, os.environ)
    if SAFE_RUN_NAME.fullmatch(save_to) is None:
        raise Tau3RunError("save-to must be a simple new run name")
    plan = load_plan(plan_path)
    manifest = load_manifest(manifest_path)
    verify_plan(plan, manifest, manifest_path)
    audit_source(source_root)

    output_dir = source_root / "data" / "simulations" / save_to
    if output_dir.exists():
        raise Tau3RunError("save-to already exists; paid results are never overwritten")

    secret = os.environ["DEEPSEEK_API_KEY"]
    os.environ["OPENAI_API_KEY"] = secret
    os.environ["OPENAI_API_BASE"] = "https://api.deepseek.com"
    os.environ["LANGSMITH_TRACING"] = "false"

    evaluator_module = _install_tau3_adapter(plan, source_root)
    evaluator_usage = _capture_evaluator_usage(evaluator_module)

    from tau2.data_model.simulation import (
        TextRunConfig,  # type: ignore[import-not-found]
    )
    from tau2.run import run_domain  # type: ignore[import-not-found]

    config = TextRunConfig(
        domain="retail",
        task_split_name="train",
        task_ids=[task.task_id for task in plan.tasks],
        agent=plan.agent_implementation,
        llm_agent=plan.agent_model,
        llm_args_agent={"temperature": 0, "parallel_tool_calls": False},
        user="user_simulator",
        llm_user=plan.user_model,
        llm_args_user={"temperature": 0},
        num_trials=plan.attempts_per_task,
        max_steps=plan.max_steps,
        enforce_communication_protocol=True,
        save_to=save_to,
        max_concurrency=plan.max_concurrency,
        max_retries=plan.max_retries,
        retry_delay=0,
        auto_resume=False,
        auto_review=False,
        review_model=plan.evaluator_model,
        hallucination_retries=plan.hallucination_retries,
        seed=plan.seed,
    )
    try:
        run_domain(config)
    finally:
        if output_dir.exists():
            metadata = output_dir / "trace2flow-run-metadata.json"
            if not metadata.exists():
                _write_private_metadata(metadata, plan_path, evaluator_usage)
    return output_dir / "results.json"


def _usage(messages: list[Mapping[str, Any]], role: str) -> dict[str, Any]:
    role_messages = [message for message in messages if message.get("role") == role]
    measured = [message.get("usage") for message in role_messages if message.get("usage")]
    return {
        "trajectory_messages": len(role_messages),
        "reported_usage_messages": len(measured),
        "reported_prompt_tokens": sum(item.get("prompt_tokens", 0) for item in measured),
        "reported_completion_tokens": sum(
            item.get("completion_tokens", 0) for item in measured
        ),
    }


def build_public_report(
    plan_path: Path,
    manifest_path: Path,
    results_path: Path,
    private_metadata_path: Path,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    manifest = load_manifest(manifest_path)
    verify_plan(plan, manifest, manifest_path)
    try:
        source = json.loads(results_path.read_text(encoding="utf-8"))
        metadata = json.loads(private_metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Tau3RunError(f"cannot read batch result: {type(exc).__name__}") from exc
    simulations = source.get("simulations")
    if not isinstance(simulations, list):
        raise Tau3RunError("batch results have no simulation inventory")
    by_task: dict[str, Mapping[str, Any]] = {}
    for raw in simulations:
        if not isinstance(raw, dict):
            raise Tau3RunError("simulation must be an object")
        task_id = str(raw.get("task_id"))
        if task_id in by_task:
            raise Tau3RunError(f"duplicate simulation task: {task_id}")
        by_task[task_id] = raw
    expected = {task.task_id for task in plan.tasks}
    if set(by_task) != expected:
        raise Tau3RunError("result task inventory does not exactly match the plan")
    if metadata.get("plan_sha256") != file_sha256(plan_path):
        raise Tau3RunError("private run metadata plan hash mismatch")

    evaluator_by_task: dict[str, dict[str, int]] = defaultdict_usage()
    for item in metadata.get("evaluator_usage", []):
        task_id = item.get("task_id")
        if task_id not in expected:
            raise Tau3RunError("evaluator usage references an unknown task")
        if item.get("prompt_tokens") is not None:
            evaluator_by_task[task_id]["prompt_tokens"] += int(item["prompt_tokens"])
        if item.get("completion_tokens") is not None:
            evaluator_by_task[task_id]["completion_tokens"] += int(
                item["completion_tokens"]
            )
        evaluator_by_task[task_id]["calls"] += 1

    rows = []
    for task in plan.tasks:
        simulation = by_task[task.task_id]
        messages = simulation.get("messages") or []
        reward_info = simulation.get("reward_info") or {}
        breakdown = reward_info.get("reward_breakdown") or {}
        tool_batches = [
            len(message.get("tool_calls") or [])
            for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant"
        ]
        tool_messages = [
            message
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        ]
        mixed_content_tool_messages = sum(
            bool(message.get("content")) and bool(message.get("tool_calls"))
            for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant"
        )
        error_type = None
        info = simulation.get("info")
        if isinstance(info, dict):
            value = info.get("error_type")
            error_type = str(value) if value is not None else None
        rows.append(
            {
                "task_id": task.task_id,
                "workflow_families": task.workflow_families,
                "termination_reason": simulation.get("termination_reason"),
                "error_type": error_type,
                "reward": reward_info.get("reward"),
                "db_reward": (reward_info.get("db_check") or {}).get("db_reward"),
                "nl_assertion_reward": breakdown.get("NL_ASSERTION"),
                "duration_seconds": simulation.get("duration"),
                "agent_usage": _usage(messages, "assistant"),
                "user_usage": _usage(messages, "user"),
                "evaluator_usage": evaluator_by_task[task.task_id],
                "tool_call_count": len(tool_messages),
                "tool_error_count": sum(bool(item.get("error")) for item in tool_messages),
                "max_tool_calls_in_one_assistant_message": max(tool_batches or [0]),
                "mixed_content_tool_messages": mixed_content_tool_messages,
                "single_tool_call_guard_failure": (
                    simulation.get("termination_reason") == "infrastructure_error"
                    and error_type in {"Tau3RunError", "Tau3SingleCallViolation"}
                ),
            }
        )
    rewards = [row["reward"] for row in rows if row["reward"] is not None]
    agent_prompt = sum(
        row["agent_usage"]["reported_prompt_tokens"] for row in rows
    )
    agent_completion = sum(
        row["agent_usage"]["reported_completion_tokens"] for row in rows
    )
    user_prompt = sum(row["user_usage"]["reported_prompt_tokens"] for row in rows)
    user_completion = sum(
        row["user_usage"]["reported_completion_tokens"] for row in rows
    )
    evaluator_prompt = sum(row["evaluator_usage"]["prompt_tokens"] for row in rows)
    evaluator_completion = sum(
        row["evaluator_usage"]["completion_tokens"] for row in rows
    )
    successful_results = sum(reward == 1 for reward in rewards)
    policy_violations = sum(
        row["single_tool_call_guard_failure"]
        or row["mixed_content_tool_messages"] > 0
        for row in rows
    )
    gate_configured = (
        plan.test_gate_min_successful_results is not None
        and plan.test_gate_max_policy_violations is not None
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "dataset": plan.dataset,
        "evaluation_role": "development_not_holdout",
        "source_commit": plan.source_commit,
        "plan_sha256": file_sha256(plan_path),
        "manifest_sha256": file_sha256(manifest_path),
        "results_sha256": file_sha256(results_path),
        "private_metadata_sha256": file_sha256(private_metadata_path),
        "planned_tasks": len(plan.tasks),
        "retained_results": len(rows),
        "evaluated_results": len(rewards),
        "successful_results": successful_results,
        "mean_reward": sum(rewards) / len(rewards) if rewards else None,
        "policy_violations": policy_violations,
        "test_open_gate": {
            "configured": gate_configured,
            "min_successful_results": plan.test_gate_min_successful_results,
            "max_policy_violations": plan.test_gate_max_policy_violations,
            "passed": (
                successful_results >= plan.test_gate_min_successful_results
                and policy_violations <= plan.test_gate_max_policy_violations
            )
            if gate_configured
            else None,
        },
        "termination_counts": dict(
            sorted(Counter(str(row["termination_reason"]) for row in rows).items())
        ),
        "reported_usage": {
            "agent": {
                "prompt_tokens": agent_prompt,
                "completion_tokens": agent_completion,
            },
            "user_simulator": {
                "prompt_tokens": user_prompt,
                "completion_tokens": user_completion,
            },
            "nl_evaluator": {
                "prompt_tokens": evaluator_prompt,
                "completion_tokens": evaluator_completion,
                "calls": sum(row["evaluator_usage"]["calls"] for row in rows),
            },
        },
        "cost_claim": "not_computed",
        "results": rows,
        "limitations": [
            "Development results are not a held-out benchmark estimate.",
            "The batch uses a simulated user and simulated retail backend, not real customers.",
            "Token fields report provider metadata where available; money cost is not estimated.",
            "No Trace2Flow workflow is evaluated by this Agent-baseline batch.",
        ],
    }


def defaultdict_usage() -> dict[str, dict[str, int]]:
    class UsageDict(dict):
        def __missing__(self, key):
            value = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
            self[key] = value
            return value

    return UsageDict()


def write_json_exclusive(value: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or publish a frozen τ³ batch")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("plan", type=Path)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--source-root", type=Path, required=True)
    run.add_argument("--save-to", required=True)
    run.add_argument("--allow-paid-call", action="store_true")
    publish = subparsers.add_parser("publish")
    publish.add_argument("plan", type=Path)
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--results", type=Path, required=True)
    publish.add_argument("--private-metadata", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_paid_batch(
                args.plan,
                args.manifest,
                args.source_root,
                args.save_to,
                allow_paid_call=args.allow_paid_call,
            )
            print(json.dumps({"results": str(result)}, sort_keys=True))
        else:
            report = build_public_report(
                args.plan,
                args.manifest,
                args.results,
                args.private_metadata,
            )
            write_json_exclusive(report, args.output)
            print(
                json.dumps(
                    {
                        "evaluated": report["evaluated_results"],
                        "retained": report["retained_results"],
                        "successful": report["successful_results"],
                    },
                    sort_keys=True,
                )
            )
    except (Tau3RunError, FileExistsError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

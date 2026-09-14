"""Safe subprocess boundary for the audited upstream ASP compiler."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .asp import to_asp
from .models import DatasetPartition, StrictModel, TraceDataset

UPSTREAM_BASELINE_COMMIT = "b168d6760213b489e2fb2f5571f5d4e6d648dee8"


class RuleProfile(str, Enum):
    STRICT = "strict"
    RELAXED = "relaxed"

    @property
    def filename(self) -> str:
        if self is RuleProfile.STRICT:
            return "mine_patterns.lp"
        return "mine_patterns_relaxed.lp"


class UpstreamCompilationError(RuntimeError):
    """The pinned upstream compiler failed or returned an invalid result."""


class UpstreamConditional(StrictModel):
    tool: str
    depends_on: str
    rate: str


class UpstreamSignals(StrictModel):
    """Normalized tool-level signals retained from upstream output."""

    source_sha256: str
    rules_sha256: str
    baseline_commit: Literal["b168d6760213b489e2fb2f5571f5d4e6d648dee8"] = (
        UPSTREAM_BASELINE_COMMIT
    )
    compiler_sha256: str
    rule_profile: RuleProfile = Field(strict=False)
    source_runs: int
    compiled_call_count: int
    core_tools: list[str]
    phases: dict[int, list[str]]
    conditionals: list[UpstreamConditional]
    fusion_candidates: list[tuple[str, str]]
    mutually_exclusive: list[tuple[str, str]]
    conflicting_order_choices: list[str]
    variable_params: dict[str, list[str]]


@dataclass(frozen=True)
class UpstreamCompilation:
    compiled: dict[str, Any]
    signals: UpstreamSignals


def _pair_list(value: Any, field_name: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise UpstreamCompilationError(f"upstream field '{field_name}' is not a list")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            raise UpstreamCompilationError(
                f"upstream field '{field_name}' contains an invalid pair"
            )
        pairs.append((item[0], item[1]))
    return sorted(pairs)


def _normalize_signals(
    compiled: dict[str, Any],
    *,
    source_sha256: str,
    compiler_sha256: str,
    rules_sha256: str,
    rule_profile: RuleProfile,
) -> UpstreamSignals:
    try:
        metadata = compiled["_autocompile"]
        analysis = compiled["_analysis"]
        calls = compiled["calls"]
        source_runs = metadata["source_runs"]
        core_tools = metadata["core_tools"]
        raw_phases = metadata["phases"]
    except (KeyError, TypeError) as exc:
        raise UpstreamCompilationError(
            f"upstream result is missing required field: {exc}"
        ) from None

    if not isinstance(metadata, dict) or not isinstance(analysis, dict):
        raise UpstreamCompilationError("upstream metadata/analysis must be objects")
    if not isinstance(calls, list) or not isinstance(source_runs, int):
        raise UpstreamCompilationError("upstream calls/source_runs have invalid types")
    if not isinstance(core_tools, list) or not all(
        isinstance(tool, str) for tool in core_tools
    ):
        raise UpstreamCompilationError("upstream core_tools must be strings")
    if not isinstance(raw_phases, dict):
        raise UpstreamCompilationError("upstream phases must be an object")

    phases: dict[int, list[str]] = {}
    for phase, tools in raw_phases.items():
        if not isinstance(tools, list) or not all(
            isinstance(tool, str) for tool in tools
        ):
            raise UpstreamCompilationError("upstream phase tools must be strings")
        try:
            phase_number = int(phase)
        except (TypeError, ValueError):
            raise UpstreamCompilationError(
                f"upstream phase key is not an integer: {phase!r}"
            ) from None
        phases[phase_number] = sorted(tools)

    conditionals: list[UpstreamConditional] = []
    raw_conditionals = analysis.get("conditionals", [])
    if not isinstance(raw_conditionals, list):
        raise UpstreamCompilationError("upstream conditionals must be a list")
    for item in raw_conditionals:
        if not isinstance(item, dict):
            raise UpstreamCompilationError("upstream conditional must be an object")
        try:
            conditionals.append(
                UpstreamConditional(
                    tool=item["tool"],
                    depends_on=item["depends_on"],
                    rate=item["rate"],
                )
            )
        except (KeyError, TypeError, ValueError):
            raise UpstreamCompilationError(
                "upstream conditional has invalid fields"
            ) from None

    raw_choices = analysis.get("conflicting_orders_resolved", [])
    if not isinstance(raw_choices, list):
        raise UpstreamCompilationError(
            "upstream conflicting_orders_resolved must be a list"
        )
    choices: list[str] = []
    for item in raw_choices:
        if not isinstance(item, dict) or not isinstance(item.get("chose"), str):
            raise UpstreamCompilationError("upstream order choice is invalid")
        choices.append(item["chose"])

    raw_variable_params = analysis.get("variable_params", {})
    if not isinstance(raw_variable_params, dict):
        raise UpstreamCompilationError("upstream variable_params must be an object")
    variable_params: dict[str, list[str]] = {}
    for tool, keys in raw_variable_params.items():
        if not isinstance(tool, str) or not isinstance(keys, list) or not all(
            isinstance(key, str) for key in keys
        ):
            raise UpstreamCompilationError("upstream variable_params is invalid")
        variable_params[tool] = sorted(keys)

    return UpstreamSignals(
        source_sha256=source_sha256,
        compiler_sha256=compiler_sha256,
        rules_sha256=rules_sha256,
        rule_profile=rule_profile,
        source_runs=source_runs,
        compiled_call_count=len(calls),
        core_tools=sorted(core_tools),
        phases=dict(sorted(phases.items())),
        conditionals=sorted(
            conditionals,
            key=lambda item: (item.tool, item.depends_on, item.rate),
        ),
        fusion_candidates=_pair_list(
            analysis.get("fusion_candidates", []), "fusion_candidates"
        ),
        mutually_exclusive=_pair_list(
            analysis.get("mutually_exclusive", []), "mutually_exclusive"
        ),
        conflicting_order_choices=sorted(choices),
        variable_params=dict(sorted(variable_params.items())),
    )


def compile_with_upstream(
    dataset: TraceDataset,
    rule_profile: RuleProfile = RuleProfile.STRICT,
) -> UpstreamCompilation:
    """Run only the pinned local compiler and one allowlisted rules profile."""

    if dataset.partition is not DatasetPartition.COMPILE:
        raise ValueError("upstream mining requires a dataset partitioned as 'compile'")

    project_root = Path(__file__).resolve().parents[2]
    compiler_path = project_root / "src" / "compile.py"
    rules_path = project_root / "rules" / rule_profile.filename
    bundle = to_asp(dataset)
    compiler_sha256 = hashlib.sha256(compiler_path.read_bytes()).hexdigest()
    rules_sha256 = hashlib.sha256(rules_path.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory(prefix="trace2flow-upstream-") as tempdir:
        temp_path = Path(tempdir)
        traces_path = temp_path / "traces.lp"
        output_path = temp_path / "compiled.json"
        bundle.write(traces_path)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(compiler_path),
                    "--traces",
                    str(traces_path),
                    "--rules",
                    str(rules_path),
                    "--output",
                    str(output_path),
                ],
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise UpstreamCompilationError(
                "upstream compiler exceeded the 60 second safety timeout"
            ) from exc

        if result.returncode != 0:
            diagnostic = (result.stderr or result.stdout).strip()
            raise UpstreamCompilationError(
                f"upstream compiler exited {result.returncode}: {diagnostic[-2000:]}"
            )
        try:
            compiled = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpstreamCompilationError(
                "upstream compiler did not produce valid JSON"
            ) from exc
        if not isinstance(compiled, dict):
            raise UpstreamCompilationError("upstream result must be a JSON object")

    return UpstreamCompilation(
        compiled=compiled,
        signals=_normalize_signals(
            compiled,
            source_sha256=bundle.source_sha256,
            compiler_sha256=compiler_sha256,
            rules_sha256=rules_sha256,
            rule_profile=rule_profile,
        ),
    )

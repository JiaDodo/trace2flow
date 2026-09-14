"""Strict loading and deterministic serialization for normalized traces."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import TraceDataset


class TraceFormatError(ValueError):
    """A stable, user-facing error for invalid normalized trace data."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TraceFormatError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise TraceFormatError(f"non-finite JSON number is not allowed: {value}")


def _format_validation_error(error: ValidationError) -> str:
    formatted: list[tuple[str, str]] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        formatted.append((location, item["msg"]))
    return "invalid trace dataset:\n" + "\n".join(
        f"- {location}: {message}" for location, message in sorted(formatted)
    )


def loads_trace_dataset(text: str) -> TraceDataset:
    """Load the normalized schema while rejecting JSON extensions and duplicates."""

    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except TraceFormatError:
        raise
    except json.JSONDecodeError as exc:
        raise TraceFormatError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from None

    try:
        return TraceDataset.model_validate(value)
    except ValidationError as exc:
        raise TraceFormatError(_format_validation_error(exc)) from None


def load_trace_dataset(path: str | Path) -> TraceDataset:
    return loads_trace_dataset(Path(path).read_text(encoding="utf-8"))


def canonical_json(dataset: TraceDataset) -> str:
    """Serialize deterministically while retaining JSON value types and list order."""

    return (
        json.dumps(
            dataset.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def dump_trace_dataset(dataset: TraceDataset, path: str | Path) -> None:
    Path(path).write_text(canonical_json(dataset), encoding="utf-8")

"""Allowlisted runtime primitives shared by generated targets and simulation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import JsonValue

from .models import json_compatible

ToolCallable = Callable[..., JsonValue]


class UnregisteredToolError(LookupError):
    """Raised before dispatch when a workflow names an unknown tool."""


@dataclass
class ToolRegistry:
    """Explicit name-to-callable registry; arbitrary imports/code are unsupported."""

    _tools: dict[str, ToolCallable] = field(default_factory=dict)

    def __init__(self, tools: Mapping[str, ToolCallable] | None = None) -> None:
        self._tools = {}
        for name, tool in (tools or {}).items():
            self.register(name, tool)

    def register(self, name: str, tool: ToolCallable) -> None:
        if not name or name.strip() != name:
            raise ValueError("registered tool name must be non-empty and trimmed")
        if name in self._tools:
            raise ValueError(f"tool '{name}' is already registered")
        if not callable(tool):
            raise TypeError(f"registered tool '{name}' must be callable")
        self._tools[name] = tool

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def invoke(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        try:
            tool = self._tools[name]
        except KeyError:
            raise UnregisteredToolError(
                f"tool '{name}' is not registered; allowed tools: "
                + ", ".join(sorted(self._tools))
            ) from None
        return json_compatible(tool(**params))


def get_path(value: Any, path: list[str | int]) -> JsonValue:
    """Resolve a validated JSON-style path without evaluating expressions."""

    current = value
    for part in path:
        valid_object_key = (
            isinstance(part, str) and isinstance(current, dict) and part in current
        )
        valid_list_index = (
            isinstance(part, int)
            and not isinstance(part, bool)
            and isinstance(current, list)
            and 0 <= part < len(current)
        )
        if not (valid_object_key or valid_list_index):
            raise KeyError(f"JSON path component {part!r} is unavailable")
        current = current[part]
    return json_compatible(current)

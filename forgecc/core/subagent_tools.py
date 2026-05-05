"""Tool-set resolution for sub-agent execution."""

from __future__ import annotations

from collections.abc import Iterable


RECURSIVE_AGENT_TOOLS = {"agent", "team"}


def resolve_sub_agent_tool_names(
    available_tools: Iterable[str],
    configured_tools: set[str] | None,
    allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
) -> set[str]:
    """Resolve the tool names a sub-agent may use."""
    if configured_tools is None:
        tool_names = set(available_tools)
    else:
        tool_names = set(configured_tools)

    if allowed_tools is not None:
        tool_names &= set(allowed_tools)

    return tool_names - RECURSIVE_AGENT_TOOLS

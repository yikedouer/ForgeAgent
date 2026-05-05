"""MCP tool bridge helpers for the toolkit catalog."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]
    readonly: bool = True
    risk_level: str = "read"


def build_mcp_tool_specs(server_name: str, client: object) -> tuple[MCPToolSpec, ...]:
    """Build toolkit-ready specs for tools exposed by an initialized MCP client."""
    if not isinstance(server_name, str) or not server_name.strip():
        raise ValueError("MCP server name must be a non-empty string")
    if not hasattr(client, "list_tools") or not hasattr(client, "call_tool"):
        raise ValueError("MCP client must provide list_tools() and call_tool()")

    safe_server = _safe_tool_name(server_name)
    specs: list[MCPToolSpec] = []
    for remote_tool in client.list_tools():
        remote_name = getattr(remote_tool, "name", "")
        if not isinstance(remote_name, str) or not remote_name.strip():
            raise ValueError("MCP tool name must be a non-empty string")
        tool_name = f"mcp__{safe_server}__{_safe_tool_name(remote_name)}"
        description = getattr(remote_tool, "description", "") or remote_name
        input_schema = getattr(remote_tool, "input_schema", None)
        parameters = copy.deepcopy(input_schema) if isinstance(input_schema, dict) else {"type": "object"}

        def make_runner(tool_name: str) -> Callable[..., str]:
            def runner(**kwargs) -> str:
                return _format_mcp_result(client.call_tool(tool_name, kwargs))
            return runner

        specs.append(MCPToolSpec(
            name=tool_name,
            description=f"MCP {server_name.strip()}: {description}",
            parameters=parameters,
            handler=make_runner(remote_name.strip()),
        ))
    return tuple(specs)


def _safe_tool_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "tool"


def _format_mcp_result(result: object) -> str:
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            texts = [
                item.get("text")
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ]
            if texts and len(texts) == len(content):
                return "\n".join(texts)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

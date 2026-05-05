"""MCP server configuration parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


def parse_mcp_servers(raw: str) -> tuple[MCPServerConfig, ...]:
    """Parse a Claude-style MCP server JSON object.

    Accepted shapes:
      * {"server": {"command": "...", "args": [...], "env": {...}}}
      * {"mcpServers": {"server": {...}}}
    """
    raw = raw.strip() if isinstance(raw, str) else ""
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid MCP servers JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP servers config must be a JSON object")

    servers = payload.get("mcpServers", payload)
    if not isinstance(servers, dict):
        raise ValueError("MCP servers config must contain an object")

    return tuple(
        _parse_server(name, config)
        for name, config in servers.items()
    )


def _parse_server(name: Any, config: Any) -> MCPServerConfig:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("MCP server name must be a non-empty string")
    if not isinstance(config, dict):
        raise ValueError(f"MCP server {name!r} must be an object")

    command = config.get("command", "")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"MCP server {name!r} command must be a non-empty string")

    return MCPServerConfig(
        name=name.strip(),
        command=command.strip(),
        args=_string_tuple(config.get("args", ()), f"MCP server {name!r} args"),
        env=_env_tuple(config.get("env", {}), name),
    )


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{label} must be an array of strings")
        result.append(item)
    return tuple(result)


def _env_tuple(value: Any, name: str) -> tuple[tuple[str, str], ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, dict):
        raise ValueError(f"MCP server {name!r} env must be an object")
    result: list[tuple[str, str]] = []
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"MCP server {name!r} env must contain string pairs")
        result.append((key, item))
    return tuple(result)

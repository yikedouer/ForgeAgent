"""MCP client facade and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mcp import ClientSession
from mcp.types import CallToolResult, ListToolsResult, Tool

from .config import MCPServerConfig


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


class MCPProtocolError(RuntimeError):
    """Raised when the MCP SDK returns invalid data or fails a request."""


class MCPTransport(Protocol):
    streams: tuple[Any, Any]
    _portal: Any


class MCPClient:
    """Small synchronous facade over the official MCP SDK client session."""

    def __init__(self, config: MCPServerConfig, transport: MCPTransport):
        self.config = config
        self.transport = transport
        read_stream, write_stream = transport.streams
        self._session_cm = transport._portal.wrap_async_context_manager(
            ClientSession(read_stream, write_stream)
        )
        self._session = self._session_cm.__enter__()
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        result = self._call(self._session.initialize)
        self._initialized = True
        return _dump_result(result)

    def list_tools(self) -> tuple[MCPTool, ...]:
        self._ensure_initialized()
        result = self._call(self._session.list_tools)
        tools = result.tools if isinstance(result, ListToolsResult) else _dump_result(result).get("tools", [])
        return tuple(_parse_tool(tool) for tool in tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("MCP tool name must be a non-empty string")
        self._ensure_initialized()
        result = self._call(self._session.call_tool, name.strip(), arguments or {})
        return _dump_result(result)

    def close(self) -> None:
        self._session_cm.__exit__(None, None, None)

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _call(self, fn: Any, *args: Any) -> Any:
        try:
            return self.transport._portal.call(fn, *args)
        except Exception as exc:
            raise MCPProtocolError(str(exc)) from exc


def _parse_tool(tool: Any) -> MCPTool:
    if isinstance(tool, Tool):
        return MCPTool(
            name=tool.name.strip(),
            description=tool.description or "",
            input_schema=tool.inputSchema,
        )
    if not isinstance(tool, dict):
        raise MCPProtocolError("MCP tool entry must be an object")
    name = tool.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise MCPProtocolError("MCP tool entry must include a non-empty name")
    description = tool.get("description", "")
    input_schema = tool.get("inputSchema")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise MCPProtocolError("MCP tool description must be a string")
    if input_schema is not None and not isinstance(input_schema, dict):
        raise MCPProtocolError("MCP tool inputSchema must be an object")
    return MCPTool(
        name=name.strip(),
        description=description,
        input_schema=input_schema,
    )


def _dump_result(result: Any) -> dict[str, Any]:
    if isinstance(result, CallToolResult):
        return result.model_dump(by_alias=True, exclude_none=True)
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(by_alias=True, exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    if isinstance(result, dict):
        return result
    raise MCPProtocolError("MCP SDK result must be an object")

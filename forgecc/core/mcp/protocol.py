"""MCP JSON-RPC protocol client and types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import MCPServerConfig


MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


class MCPProtocolError(RuntimeError):
    """Raised when an MCP JSON-RPC response is invalid or contains an error."""


class MCPTransport(Protocol):
    def exchange(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return the matching response."""

    def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC notification."""


class MCPClient:
    """Small synchronous MCP JSON-RPC client.

    Process management and stdio framing are intentionally delegated to the
    transport so protocol behavior stays independently testable.
    """

    def __init__(self, config: MCPServerConfig, transport: MCPTransport):
        self.config = config
        self.transport = transport
        self._next_id = 1
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ForgeCC", "version": "0"},
            },
        )
        self.transport.send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        self._initialized = True
        return result

    def list_tools(self) -> tuple[MCPTool, ...]:
        self._ensure_initialized()
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPProtocolError("MCP tools/list result must contain a tools array")
        return tuple(_parse_tool(tool) for tool in tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("MCP tool name must be a non-empty string")
        self._ensure_initialized()
        return self._request(
            "tools/call",
            {"name": name.strip(), "arguments": arguments or {}},
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        response = self.transport.exchange({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        })
        return _response_result(response, request_id)


def _parse_tool(tool: Any) -> MCPTool:
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


def _response_result(response: Any, request_id: int) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise MCPProtocolError("MCP response must be an object")
    if response.get("id") != request_id:
        raise MCPProtocolError("MCP response id did not match request id")
    error = response.get("error")
    if error is not None:
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            raise MCPProtocolError(error["message"])
        raise MCPProtocolError("MCP response contained an error")
    result = response.get("result", {})
    if not isinstance(result, dict):
        raise MCPProtocolError("MCP response result must be an object")
    return result

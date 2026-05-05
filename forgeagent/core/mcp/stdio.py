"""Synchronous wrapper around the official MCP stdio client."""

from __future__ import annotations

from typing import Any

from anyio.from_thread import start_blocking_portal
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import MCPServerConfig


class StdioMCPTransport:
    """Owns an official SDK stdio transport inside a blocking portal."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        self._stdio_cm = self._portal.wrap_async_context_manager(
            stdio_client(_server_params(config))
        )
        self.streams = self._stdio_cm.__enter__()

    def close(self) -> None:
        try:
            self._stdio_cm.__exit__(None, None, None)
        finally:
            self._portal_cm.__exit__(None, None, None)


def _server_params(config: MCPServerConfig) -> StdioServerParameters:
    return StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) or None,
    )

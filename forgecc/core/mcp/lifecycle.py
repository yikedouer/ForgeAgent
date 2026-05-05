"""MCP server lifecycle management."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .config import MCPServerConfig
from .protocol import MCPClient
from .stdio import StdioMCPTransport


class MCPServerManager:
    """Start configured MCP servers, register their tools, and close transports."""

    def __init__(
        self,
        servers: Iterable[MCPServerConfig],
        *,
        register_mcp_tools: Callable[[str, object], tuple[str, ...]],
        transport_factory: Callable[[MCPServerConfig], StdioMCPTransport] = StdioMCPTransport,
        client_factory: Callable[[MCPServerConfig, object], MCPClient] = MCPClient,
        logger: Any | None = None,
    ):
        self.servers = tuple(servers)
        self.register_mcp_tools = register_mcp_tools
        self.transport_factory = transport_factory
        self.client_factory = client_factory
        self.logger = logger
        self.transports: list[object] = []
        self.clients: list[object] = []

    def start(self) -> None:
        for config in self.servers:
            transport = None
            client = None
            try:
                transport = self.transport_factory(config)
                client = self.client_factory(config, transport)
                client.initialize()
                self.register_mcp_tools(config.name, client)
                self.clients.append(client)
                self.transports.append(transport)
            except Exception as exc:
                if client is not None:
                    try:
                        close = getattr(client, "close", None)
                        if callable(close):
                            close()
                    except Exception:
                        pass
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        pass
                self._warning("加载 MCP server 失败: %s — %s", config.name, exc)

    def close(self) -> None:
        for client in self.clients:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception as exc:
                self._warning("关闭 MCP client 失败: %s", exc)
        self.clients.clear()
        for transport in self.transports:
            try:
                transport.close()
            except Exception as exc:
                self._warning("关闭 MCP transport 失败: %s", exc)
        self.transports.clear()

    def _warning(self, message: str, *args: object) -> None:
        warning = getattr(self.logger, "warning", None)
        if callable(warning):
            warning(message, *args)

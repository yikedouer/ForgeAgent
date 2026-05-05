"""test_mcp.py - MCP server configuration parsing tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class FakeSessionContext:
    def __init__(self, session):
        self.session = session
        self.exited = False

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        self.exited = True


class FakePortal:
    def __init__(self, session):
        self.session = session
        self.context = FakeSessionContext(session)

    def wrap_async_context_manager(self, _cm):
        return self.context

    def call(self, fn, *args):
        return fn(*args)


class FakeSDKTransport:
    def __init__(self, session):
        self.streams = ("read", "write")
        self._portal = FakePortal(session)


class FakeMCPSession:
    def __init__(self, *, init_result=None, tools=None, call_result=None, error=None):
        self.init_result = init_result or {}
        self.tools = tools or []
        self.call_result = call_result or {}
        self.error = error
        self.calls = []

    def initialize(self):
        self.calls.append(("initialize",))
        if self.error:
            raise self.error
        return self.init_result

    def list_tools(self):
        self.calls.append(("list_tools",))
        return {"tools": self.tools}

    def call_tool(self, name, arguments=None):
        self.calls.append(("call_tool", name, arguments))
        return self.call_result


class TestParseMCPServers:
    def test_blank_config_returns_no_servers(self):
        from forgecc.core.mcp import parse_mcp_servers

        assert parse_mcp_servers("") == ()

    def test_parses_named_command_server(self):
        from forgecc.core.mcp import MCPServerConfig, parse_mcp_servers

        servers = parse_mcp_servers(
            """
            {
              "filesystem": {
                "command": "uvx",
                "args": ["mcp-server-filesystem", "/tmp"],
                "env": {"TOKEN": "secret"}
              }
            }
            """,
        )

        assert servers == (
            MCPServerConfig(
                name="filesystem",
                command="uvx",
                args=("mcp-server-filesystem", "/tmp"),
                env=(("TOKEN", "secret"),),
            ),
        )

    def test_parses_mcp_servers_wrapper_object(self):
        from forgecc.core.mcp import parse_mcp_servers

        servers = parse_mcp_servers(
            """
            {
              "mcpServers": {
                "docs": {"command": "node", "args": ["server.js"]}
              }
            }
            """,
        )

        assert len(servers) == 1
        assert servers[0].name == "docs"
        assert servers[0].command == "node"
        assert servers[0].args == ("server.js",)

    def test_rejects_non_string_command(self):
        from forgecc.core.mcp import parse_mcp_servers

        with pytest.raises(ValueError, match="command"):
            parse_mcp_servers('{"bad": {"command": ["uvx"]}}')

    def test_rejects_invalid_json(self):
        from forgecc.core.mcp import parse_mcp_servers

        with pytest.raises(ValueError, match="JSON"):
            parse_mcp_servers("{not json}")


class TestMCPClient:
    def test_initialize_uses_sdk_session(self, monkeypatch):
        from forgecc.core.mcp import MCPClient, MCPServerConfig
        from forgecc.core.mcp import protocol as protocol_mod

        session = FakeMCPSession(init_result={"serverInfo": {"name": "fake"}})
        monkeypatch.setattr(protocol_mod, "ClientSession", lambda *_args: session)
        transport = FakeSDKTransport(session)
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        result = client.initialize()

        assert result == {"serverInfo": {"name": "fake"}}
        assert session.calls == [("initialize",)]

    def test_list_tools_initializes_and_returns_normalized_tools(self, monkeypatch):
        from forgecc.core.mcp import MCPClient, MCPServerConfig, MCPTool
        from forgecc.core.mcp import protocol as protocol_mod

        session = FakeMCPSession(tools=[{
            "name": "search_docs",
            "description": "Search docs",
            "inputSchema": {"type": "object"},
        }])
        monkeypatch.setattr(protocol_mod, "ClientSession", lambda *_args: session)
        transport = FakeSDKTransport(session)
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        assert client.list_tools() == (
            MCPTool(
                name="search_docs",
                description="Search docs",
                input_schema={"type": "object"},
            ),
        )
        assert session.calls == [("initialize",), ("list_tools",)]

    def test_call_tool_sends_name_and_arguments(self, monkeypatch):
        from forgecc.core.mcp import MCPClient, MCPServerConfig
        from forgecc.core.mcp import protocol as protocol_mod

        session = FakeMCPSession(call_result={"content": [{"type": "text", "text": "done"}]})
        monkeypatch.setattr(protocol_mod, "ClientSession", lambda *_args: session)
        transport = FakeSDKTransport(session)
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        result = client.call_tool("search_docs", {"query": "ForgeCC"})

        assert result == {"content": [{"type": "text", "text": "done"}]}
        assert session.calls == [
            ("initialize",),
            ("call_tool", "search_docs", {"query": "ForgeCC"}),
        ]

    def test_sdk_error_raises_protocol_error(self, monkeypatch):
        from forgecc.core.mcp import MCPClient, MCPProtocolError, MCPServerConfig
        from forgecc.core.mcp import protocol as protocol_mod

        session = FakeMCPSession(error=RuntimeError("server failed"))
        monkeypatch.setattr(protocol_mod, "ClientSession", lambda *_args: session)
        transport = FakeSDKTransport(session)
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        with pytest.raises(MCPProtocolError, match="server failed"):
            client.initialize()


def test_mcp_protocol_types_are_exported_from_core_package():
    from forgecc.core import (
        MCPClient, MCPProtocolError, MCPTool, MCPTransport, StdioMCPTransport,
    )

    assert MCPClient is not None
    assert MCPProtocolError is not None
    assert MCPTool is not None
    assert MCPTransport is not None
    assert StdioMCPTransport is not None


def test_mcp_concerns_are_importable_from_focused_modules():
    from forgecc.core.mcp import MCPClient, MCPServerConfig, MCPServerManager, StdioMCPTransport
    from forgecc.core.mcp.config import MCPServerConfig as ConfigServerConfig
    from forgecc.core.mcp.lifecycle import MCPServerManager as LifecycleManager
    from forgecc.core.mcp.protocol import MCPClient as ProtocolClient
    from forgecc.core.mcp.stdio import StdioMCPTransport as StdioTransport

    assert ConfigServerConfig is MCPServerConfig
    assert LifecycleManager is MCPServerManager
    assert ProtocolClient is MCPClient
    assert StdioTransport is StdioMCPTransport


class TestMCPServerManager:
    def test_start_initializes_registers_and_tracks_transports(self):
        from forgecc.core.mcp import MCPServerConfig
        from forgecc.core.mcp.lifecycle import MCPServerManager

        config = MCPServerConfig(name="docs", command="uvx")
        transport = MagicMock()
        client = MagicMock()
        transport_factory = MagicMock(return_value=transport)
        client_factory = MagicMock(return_value=client)
        register = MagicMock(return_value=("mcp__docs__search",))

        manager = MCPServerManager(
            (config,),
            register_mcp_tools=register,
            transport_factory=transport_factory,
            client_factory=client_factory,
        )

        manager.start()

        transport_factory.assert_called_once_with(config)
        client_factory.assert_called_once_with(config, transport)
        client.initialize.assert_called_once_with()
        register.assert_called_once_with("docs", client)
        assert manager.transports == [transport]

    def test_start_closes_transport_when_registration_fails(self):
        from forgecc.core.mcp import MCPServerConfig
        from forgecc.core.mcp.lifecycle import MCPServerManager

        config = MCPServerConfig(name="docs", command="uvx")
        transport = MagicMock()
        client = MagicMock()

        manager = MCPServerManager(
            (config,),
            register_mcp_tools=MagicMock(side_effect=RuntimeError("boom")),
            transport_factory=MagicMock(return_value=transport),
            client_factory=MagicMock(return_value=client),
        )

        manager.start()

        transport.close.assert_called_once_with()
        assert manager.transports == []

    def test_close_releases_tracked_transports(self):
        from forgecc.core.mcp.lifecycle import MCPServerManager

        transport = MagicMock()
        manager = MCPServerManager((), register_mcp_tools=MagicMock())
        manager.transports.append(transport)

        manager.close()

        transport.close.assert_called_once_with()
        assert manager.transports == []


class TestStdioMCPTransport:
    def test_transport_uses_official_sdk_server_parameters(self, monkeypatch):
        from forgecc.core import mcp as mcp_pkg
        from forgecc.core.mcp import MCPServerConfig, StdioMCPTransport

        captured = {}

        def fake_stdio_client(params):
            captured["params"] = params

            class FakeAsyncContext:
                async def __aenter__(self):
                    return "read", "write"

                async def __aexit__(self, exc_type, exc, tb):
                    return None

            return FakeAsyncContext()

        monkeypatch.setattr(mcp_pkg.stdio, "stdio_client", fake_stdio_client)

        transport = StdioMCPTransport(
            MCPServerConfig(
                name="docs",
                command="uvx",
                args=("mcp-server", "/tmp"),
                env=(("TOKEN", "secret"),),
            ),
        )
        try:
            assert captured["params"].command == "uvx"
            assert captured["params"].args == ["mcp-server", "/tmp"]
            assert captured["params"].env == {"TOKEN": "secret"}
            assert transport.streams == ("read", "write")
        finally:
            transport.close()

    def test_client_can_call_tool_through_real_sdk_stdio_process(self, tmp_path):
        from forgecc.core.mcp import MCPClient, MCPServerConfig, StdioMCPTransport

        server = tmp_path / "mcp_server.py"
        server.write_text(
            """
from mcp.server.fastmcp import FastMCP

server = FastMCP("fake")

@server.tool()
def echo(text: str) -> str:
    return f"echo: {text}"

server.run("stdio")
""",
            encoding="utf-8",
        )
        config = MCPServerConfig(
            name="fake",
            command="uv",
            args=("run", "python", str(server)),
        )
        transport = StdioMCPTransport(config)
        client = MCPClient(config, transport)
        try:
            client.initialize()
            tools = client.list_tools()
            result = client.call_tool("echo", {"text": "ForgeCC"})
        finally:
            client.close()
            transport.close()

        assert tools[0].name == "echo"
        assert result["content"] == [{"type": "text", "text": "echo: ForgeCC"}]
        assert result["structuredContent"] == {"result": "echo: ForgeCC"}
        assert result["isError"] is False

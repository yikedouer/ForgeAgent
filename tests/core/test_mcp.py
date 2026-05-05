"""test_mcp.py - MCP server configuration parsing tests."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.notifications = []

    def exchange(self, message):
        self.requests.append(message)
        return self.responses.pop(0)

    def send(self, message):
        self.notifications.append(message)


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.flushed = False
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        self.flushed = True

    def close(self):
        self.closed = True


class FakeStdout:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        if not self.lines:
            return ""
        return self.lines.pop(0)


class FakeProcess:
    def __init__(self, lines):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True


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
    def test_initialize_sends_handshake_and_initialized_notification(self):
        from forgecc.core.mcp import MCPClient, MCPServerConfig

        transport = FakeTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "fake"}}},
        ])
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        result = client.initialize()

        assert result == {"serverInfo": {"name": "fake"}}
        assert transport.requests[0]["method"] == "initialize"
        assert transport.requests[0]["params"]["clientInfo"]["name"] == "ForgeCC"
        assert transport.notifications == [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ]

    def test_list_tools_initializes_and_returns_normalized_tools(self):
        from forgecc.core.mcp import MCPClient, MCPServerConfig, MCPTool

        transport = FakeTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "search_docs",
                            "description": "Search docs",
                            "inputSchema": {"type": "object"},
                        },
                    ],
                },
            },
        ])
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        assert client.list_tools() == (
            MCPTool(
                name="search_docs",
                description="Search docs",
                input_schema={"type": "object"},
            ),
        )
        assert [message["method"] for message in transport.requests] == [
            "initialize",
            "tools/list",
        ]

    def test_call_tool_sends_name_and_arguments(self):
        from forgecc.core.mcp import MCPClient, MCPServerConfig

        transport = FakeTransport([
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "done"}]},
            },
        ])
        client = MCPClient(MCPServerConfig(name="docs", command="uvx"), transport)

        result = client.call_tool("search_docs", {"query": "ForgeCC"})

        assert result == {"content": [{"type": "text", "text": "done"}]}
        assert transport.requests[1]["method"] == "tools/call"
        assert transport.requests[1]["params"] == {
            "name": "search_docs",
            "arguments": {"query": "ForgeCC"},
        }

    def test_error_response_raises_protocol_error(self):
        from forgecc.core.mcp import MCPClient, MCPProtocolError, MCPServerConfig

        transport = FakeTransport([
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "server failed"},
            },
        ])
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
    def test_exchange_writes_newline_delimited_json_and_reads_response(self):
        from forgecc.core.mcp import MCPServerConfig, StdioMCPTransport

        process = FakeProcess([
            '{"jsonrpc":"2.0","id":7,"result":{"ok":true}}\n',
        ])
        transport = StdioMCPTransport(
            MCPServerConfig(name="docs", command="uvx"),
            process=process,
        )

        response = transport.exchange({"jsonrpc": "2.0", "id": 7, "method": "ping"})

        assert response == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
        assert process.stdin.writes == ['{"jsonrpc":"2.0","id":7,"method":"ping"}\n']
        assert process.stdin.flushed is True

    def test_exchange_skips_notifications_until_matching_response(self):
        from forgecc.core.mcp import MCPServerConfig, StdioMCPTransport

        process = FakeProcess([
            '{"jsonrpc":"2.0","method":"notifications/progress"}\n',
            '{"jsonrpc":"2.0","id":2,"result":{}}\n',
        ])
        transport = StdioMCPTransport(
            MCPServerConfig(name="docs", command="uvx"),
            process=process,
        )

        assert transport.exchange({"jsonrpc": "2.0", "id": 2, "method": "ping"}) == {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {},
        }

    def test_send_writes_notification_without_reading_response(self):
        from forgecc.core.mcp import MCPServerConfig, StdioMCPTransport

        process = FakeProcess([])
        transport = StdioMCPTransport(
            MCPServerConfig(name="docs", command="uvx"),
            process=process,
        )

        transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        assert process.stdin.writes == [
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
        ]

    def test_exchange_raises_on_eof_before_response(self):
        from forgecc.core.mcp import (
            MCPProtocolError, MCPServerConfig, StdioMCPTransport,
        )

        transport = StdioMCPTransport(
            MCPServerConfig(name="docs", command="uvx"),
            process=FakeProcess([]),
        )

        with pytest.raises(MCPProtocolError, match="ended"):
            transport.exchange({"jsonrpc": "2.0", "id": 1, "method": "ping"})

    def test_close_closes_stdin_and_terminates_running_process(self):
        from forgecc.core.mcp import MCPServerConfig, StdioMCPTransport

        process = FakeProcess([])
        transport = StdioMCPTransport(
            MCPServerConfig(name="docs", command="uvx"),
            process=process,
        )

        transport.close()

        assert process.stdin.closed is True
        assert process.terminated is True

    def test_client_can_call_tool_through_real_stdio_process(self, tmp_path):
        from forgecc.core.mcp import MCPClient, MCPServerConfig, StdioMCPTransport

        server = tmp_path / "mcp_server.py"
        server.write_text(
            """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"serverInfo": {"name": "fake"}}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                }
            ]
        }
    elif method == "tools/call":
        text = message.get("params", {}).get("arguments", {}).get("text", "")
        result = {"content": [{"type": "text", "text": f"echo: {text}"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
""",
            encoding="utf-8",
        )
        config = MCPServerConfig(
            name="fake",
            command=sys.executable,
            args=(str(server),),
        )
        transport = StdioMCPTransport(config)
        client = MCPClient(config, transport)
        try:
            client.initialize()
            tools = client.list_tools()
            result = client.call_tool("echo", {"text": "ForgeCC"})
        finally:
            transport.close()

        assert tools[0].name == "echo"
        assert result == {"content": [{"type": "text", "text": "echo: ForgeCC"}]}

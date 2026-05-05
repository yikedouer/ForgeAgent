"""MCP-to-toolkit bridge tests."""

from forgeagent.core.mcp import MCPTool
from forgeagent.toolkit_mcp import build_mcp_tool_specs


class FakeMCPClient:
    def __init__(self, tools, result=None):
        self.tools = tuple(tools)
        self.result = result if result is not None else {"content": [{"type": "text", "text": "ok"}]}
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def test_build_mcp_tool_specs_sanitizes_names_and_preserves_schema_copy():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    client = FakeMCPClient([
        MCPTool(name="search-docs", description="Search docs", input_schema=schema),
    ])

    specs = build_mcp_tool_specs("docs", client)

    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "mcp__docs__search_docs"
    assert spec.description == "MCP docs: Search docs"
    assert spec.parameters == schema
    assert spec.parameters is not schema
    assert spec.risk_level == "read"
    assert spec.readonly is True


def test_built_mcp_runner_routes_to_original_remote_name_and_formats_text():
    client = FakeMCPClient([
        MCPTool(name="search-docs"),
    ], result={"content": [{"type": "text", "text": "found"}]})

    spec = build_mcp_tool_specs("docs", client)[0]

    assert spec.handler(query="ForgeAgent") == "found"
    assert client.calls == [("search-docs", {"query": "ForgeAgent"})]


def test_built_mcp_runner_serializes_non_text_result():
    client = FakeMCPClient([
        MCPTool(name="stats"),
    ], result={"structuredContent": {"count": 2}})

    spec = build_mcp_tool_specs("docs", client)[0]

    assert spec.handler() == '{"structuredContent":{"count":2}}'

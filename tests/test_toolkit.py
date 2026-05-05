"""test_toolkit.py — 工具注册表测试。"""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

import forgeagent.toolkit as tk
from forgeagent.toolkit import (
    ToolSpec,
    ToolResult,
    tool,
    catalog,
    lookup,
    schemas,
    set_enforcer,
    run_one,
    run_batch,
)
from forgeagent.core.hooks import clear_hooks, register_hook
from forgeagent.core.mcp import MCPTool


# ── 辅助：注册一个测试工具 ────────────────────────────────

def _register_echo():
    @tool("echo", "Echo tool", {"type": "object", "properties": {"text": {"type": "string"}}})
    def echo(text: str = "") -> str:
        return f"echo: {text}"
    return echo


def _register_readonly():
    @tool("reader", "Read tool", {}, readonly=True, risk_level="read")
    def reader() -> str:
        return "read-ok"
    return reader


def _register_failing():
    @tool("fail_tool", "Always fails", {})
    def fail_tool() -> str:
        raise RuntimeError("boom")
    return fail_tool


class FakeMCPClient:
    def __init__(self, tools, result=None):
        self.tools = tuple(tools)
        self.result = result or {"content": [{"type": "text", "text": "ok"}]}
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def _register_required():
    @tool(
        "required_tool",
        "Tool with required args",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    def required_tool(path: str) -> str:
        return f"path: {path}"
    return required_tool


def _register_typed():
    @tool(
        "typed_tool",
        "Tool with typed args",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "timeout": {"type": "integer"},
                "items": {"type": "array"},
                "options": {"type": "object"},
                "enabled": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["fast", "slow"]},
            },
        },
    )
    def typed_tool(
        path: str = "",
        timeout: int = 0,
        items: list | None = None,
        options: dict | None = None,
        enabled: bool = False,
        mode: str = "fast",
    ) -> str:
        return "typed-ok"
    return typed_tool


def _register_number_tool():
    @tool(
        "number_tool",
        "Tool with number arg",
        {
            "type": "object",
            "properties": {"ratio": {"type": "number"}},
            "required": ["ratio"],
        },
    )
    def number_tool(ratio: float) -> str:
        return f"ratio: {ratio}"
    return number_tool


def _register_nullable_tool():
    @tool(
        "nullable_tool",
        "Tool with nullable arg",
        {
            "type": "object",
            "properties": {"note": {"type": ["string", "null"]}},
        },
    )
    def nullable_tool(note: str | None = None) -> str:
        return "none" if note is None else f"note: {note}"
    return nullable_tool


def _register_anyof_tool():
    @tool(
        "anyof_tool",
        "Tool with anyOf arg",
        {
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                    ],
                },
            },
            "required": ["value"],
        },
    )
    def anyof_tool(value: str | float) -> str:
        return f"value: {value}"
    return anyof_tool


def _register_oneof_tool():
    @tool(
        "oneof_tool",
        "Tool with oneOf arg",
        {
            "type": "object",
            "properties": {
                "value": {
                    "oneOf": [
                        {"type": "integer"},
                        {"type": "boolean"},
                    ],
                },
            },
            "required": ["value"],
        },
    )
    def oneof_tool(value: int | bool) -> str:
        return f"value: {value}"
    return oneof_tool


def _register_allof_tool():
    @tool(
        "allof_tool",
        "Tool with allOf arg",
        {
            "type": "object",
            "properties": {
                "mode": {
                    "allOf": [
                        {"type": "string"},
                        {"enum": ["fast", "slow"]},
                    ],
                },
            },
            "required": ["mode"],
        },
    )
    def allof_tool(mode: str) -> str:
        return f"mode: {mode}"
    return allof_tool


def _register_not_tool():
    @tool(
        "not_tool",
        "Tool with disallowed schema",
        {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "not": {"const": "danger"},
                },
            },
            "required": ["mode"],
        },
    )
    def not_tool(mode: str) -> str:
        return f"mode: {mode}"
    return not_tool


def _register_string_length_tool():
    @tool(
        "string_length_tool",
        "Tool with string length limits",
        {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 4,
                },
            },
            "required": ["label"],
        },
    )
    def string_length_tool(label: str) -> str:
        return f"label: {label}"
    return string_length_tool


def _register_number_range_tool():
    @tool(
        "number_range_tool",
        "Tool with number range limits",
        {
            "type": "object",
            "properties": {
                "ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
            },
            "required": ["ratio"],
        },
    )
    def number_range_tool(ratio: float) -> str:
        return f"ratio: {ratio}"
    return number_range_tool


def _register_exclusive_number_range_tool():
    @tool(
        "exclusive_number_range_tool",
        "Tool with exclusive number range limits",
        {
            "type": "object",
            "properties": {
                "ratio": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "exclusiveMaximum": 1,
                },
            },
            "required": ["ratio"],
        },
    )
    def exclusive_number_range_tool(ratio: float) -> str:
        return f"ratio: {ratio}"
    return exclusive_number_range_tool


def _register_pattern_tool():
    @tool(
        "pattern_tool",
        "Tool with string pattern",
        {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "pattern": r"^[a-z][a-z0-9_]*$",
                },
            },
            "required": ["slug"],
        },
    )
    def pattern_tool(slug: str) -> str:
        return f"slug: {slug}"
    return pattern_tool


def _register_array_length_tool():
    @tool(
        "array_length_tool",
        "Tool with array length limits",
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string"},
                },
            },
            "required": ["items"],
        },
    )
    def array_length_tool(items: list[str]) -> str:
        return f"items: {len(items)}"
    return array_length_tool


def _register_prefix_items_tool():
    @tool(
        "prefix_items_tool",
        "Tool with tuple-like array args",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "minItems": 2,
                    "prefixItems": [
                        {"type": "string", "enum": ["run", "test"]},
                        {"type": "integer", "minimum": 1},
                    ],
                    "items": False,
                },
            },
            "required": ["command"],
        },
    )
    def prefix_items_tool(command: list) -> str:
        return f"command: {command[0]} {command[1]}"
    return prefix_items_tool


def _register_empty_array_tool():
    @tool(
        "empty_array_tool",
        "Tool with disallowed array items",
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": False,
                },
            },
            "required": ["items"],
        },
    )
    def empty_array_tool(items: list) -> str:
        return f"items: {len(items)}"
    return empty_array_tool


def _register_unique_items_tool():
    @tool(
        "unique_items_tool",
        "Tool with unique array items",
        {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string"},
                },
            },
            "required": ["tags"],
        },
    )
    def unique_items_tool(tags: list[str]) -> str:
        return f"tags: {len(tags)}"
    return unique_items_tool


def _register_contains_tool():
    @tool(
        "contains_tool",
        "Tool with required matching array item",
        {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "contains": {"const": "primary"},
                },
            },
            "required": ["tags"],
        },
    )
    def contains_tool(tags: list[str]) -> str:
        return f"tags: {len(tags)}"
    return contains_tool


def _register_contains_count_tool():
    @tool(
        "contains_count_tool",
        "Tool with counted matching array items",
        {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "contains": {"const": "primary"},
                    "minContains": 2,
                    "maxContains": 3,
                },
            },
            "required": ["tags"],
        },
    )
    def contains_count_tool(tags: list[str]) -> str:
        return f"tags: {len(tags)}"
    return contains_count_tool


def _register_const_tool():
    @tool(
        "const_tool",
        "Tool with const arg",
        {
            "type": "object",
            "properties": {
                "version": {
                    "type": "string",
                    "const": "v1",
                },
            },
            "required": ["version"],
        },
    )
    def const_tool(version: str) -> str:
        return f"version: {version}"
    return const_tool


def _register_multiple_of_tool():
    @tool(
        "multiple_of_tool",
        "Tool with numeric multipleOf",
        {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "multipleOf": 5,
                },
            },
            "required": ["count"],
        },
    )
    def multiple_of_tool(count: int) -> str:
        return f"count: {count}"
    return multiple_of_tool


def _register_nested():
    @tool(
        "nested_tool",
        "Tool with array item schema",
        {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "prompt": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["general", "verification"],
                            },
                        },
                        "required": ["description", "prompt"],
                    },
                },
            },
            "required": ["agents"],
        },
    )
    def nested_tool(agents: list[dict]) -> str:
        return f"nested: {len(agents)}"
    return nested_tool


def _register_object_map():
    @tool(
        "object_map_tool",
        "Tool with free-form object args",
        {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        },
    )
    def object_map_tool(options: dict) -> str:
        return f"options: {len(options)}"
    return object_map_tool


def _register_typed_object_map():
    @tool(
        "typed_object_map_tool",
        "Tool with typed free-form object args",
        {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    )
    def typed_object_map_tool(labels: dict) -> str:
        return f"labels: {len(labels)}"
    return typed_object_map_tool


def _register_sized_object_map():
    @tool(
        "sized_object_map_tool",
        "Tool with object size limits",
        {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "minProperties": 1,
                    "maxProperties": 2,
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["labels"],
        },
    )
    def sized_object_map_tool(labels: dict) -> str:
        return f"labels: {len(labels)}"
    return sized_object_map_tool


def _register_named_object_map():
    @tool(
        "named_object_map_tool",
        "Tool with object key name limits",
        {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "propertyNames": {
                        "type": "string",
                        "pattern": r"^[a-z][a-z0-9_]*$",
                    },
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["labels"],
        },
    )
    def named_object_map_tool(labels: dict) -> str:
        return f"labels: {len(labels)}"
    return named_object_map_tool


def _register_patterned_object_map():
    @tool(
        "patterned_object_map_tool",
        "Tool with pattern-based object value schemas",
        {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "patternProperties": {
                        r"^num_": {"type": "integer"},
                        r"^str_": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "required": ["labels"],
        },
    )
    def patterned_object_map_tool(labels: dict) -> str:
        return f"labels: {len(labels)}"
    return patterned_object_map_tool


def _register_strict_patterned_object_map():
    @tool(
        "strict_patterned_object_map_tool",
        "Tool with only pattern-based object keys",
        {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "patternProperties": {
                        r"^num_": {"type": "integer"},
                        r"^str_": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["labels"],
        },
    )
    def strict_patterned_object_map_tool(labels: dict) -> str:
        return f"labels: {len(labels)}"
    return strict_patterned_object_map_tool


def _register_freeform_root():
    @tool(
        "freeform_root_tool",
        "Tool with free-form root args",
        {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    )
    def freeform_root_tool(**kwargs: str) -> str:
        return f"root: {len(kwargs)}"
    return freeform_root_tool


def _register_strict_patterned_root():
    @tool(
        "strict_patterned_root_tool",
        "Tool with only pattern-based root args",
        {
            "type": "object",
            "patternProperties": {
                r"^env_": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    def strict_patterned_root_tool(**kwargs: str) -> str:
        return f"root: {len(kwargs)}"
    return strict_patterned_root_tool


def _register_dependent_required_tool():
    @tool(
        "dependent_required_tool",
        "Tool with dependent required args",
        {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string"},
                "token": {"type": "string"},
            },
            "dependentRequired": {
                "username": ["password"],
                "password": ["username"],
            },
        },
    )
    def dependent_required_tool(username: str = "", password: str = "", token: str = "") -> str:
        return f"auth: {bool(username and password)} {bool(token)}"
    return dependent_required_tool


def _register_dependent_schema_tool():
    @tool(
        "dependent_schema_tool",
        "Tool with dependent object schemas",
        {
            "type": "object",
            "properties": {
                "create": {"type": "boolean"},
                "path": {"type": "string"},
                "mode": {"type": "string"},
            },
            "dependentSchemas": {
                "create": {
                    "required": ["path"],
                    "properties": {
                        "mode": {"enum": ["file", "dir"]},
                    },
                },
            },
        },
    )
    def dependent_schema_tool(create: bool = False, path: str = "", mode: str = "") -> str:
        return f"create: {create} {path} {mode}"
    return dependent_schema_tool


def _register_conditional_schema_tool():
    @tool(
        "conditional_schema_tool",
        "Tool with conditional object schema",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["delete", "write"]},
                "path": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["action"],
            "if": {
                "properties": {"action": {"const": "delete"}},
                "required": ["action"],
                "additionalProperties": True,
            },
            "then": {
                "required": ["force"],
                "properties": {"force": {"const": True}},
                "additionalProperties": True,
            },
            "else": {
                "required": ["path"],
                "additionalProperties": True,
            },
        },
    )
    def conditional_schema_tool(action: str, path: str = "", force: bool = False) -> str:
        return f"{action}: {path} {force}"
    return conditional_schema_tool


def _register_conditional_default_additional_tool():
    @tool(
        "conditional_default_additional_tool",
        "Tool with conditional object schema defaults",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["delete", "write"]},
                "path": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["action"],
            "if": {
                "properties": {"action": {"const": "delete"}},
                "required": ["action"],
            },
            "then": {
                "properties": {"force": {"const": True}},
                "required": ["force"],
            },
            "else": {
                "required": ["path"],
            },
        },
    )
    def conditional_default_additional_tool(action: str, path: str = "", force: bool = False) -> str:
        return f"{action}: {path} {force}"
    return conditional_default_additional_tool


# ═══════════════════════════════════════════════════════════
# 2.1 数据类
# ═══════════════════════════════════════════════════════════

class TestToolSpec:
    def test_frozen(self):
        spec = ToolSpec(name="x", description="d", parameters={}, handler=lambda: "")
        with pytest.raises(FrozenInstanceError):
            spec.name = "changed"

    def test_defaults(self):
        spec = ToolSpec(name="x", description="d", parameters={}, handler=lambda: "")
        assert spec.readonly is False
        assert spec.risk_level == "write"


class TestToolResult:
    def test_default_ok(self):
        r = ToolResult(call_id="c1", name="t", output="out")
        assert r.ok is True

    def test_explicit_ok_false(self):
        r = ToolResult(call_id="c1", name="t", output="err", ok=False)
        assert r.ok is False


# ═══════════════════════════════════════════════════════════
# 2.2 @tool 装饰器
# ═══════════════════════════════════════════════════════════

class TestToolDecorator:
    def test_register_and_catalog(self):
        _register_echo()
        assert "echo" in catalog()

    def test_returns_original_function(self):
        handler = _register_echo()
        assert callable(handler)
        assert handler(text="hi") == "echo: hi"

    def test_overwrite_same_name(self):
        _register_echo()
        # 再次注册同名工具
        @tool("echo", "Overwritten", {})
        def echo_v2() -> str:
            return "v2"
        assert catalog()["echo"].description == "Overwritten"

    def test_readonly_propagation(self):
        _register_readonly()
        spec = lookup("reader")
        assert spec is not None
        assert spec.readonly is True
        assert spec.risk_level == "read"

    def test_non_string_name_rejected_without_catalog_mutation(self):
        with pytest.raises(ValueError, match="tool name"):
            @tool(["bad_name"], "Bad", {})
            def bad_name() -> str:
                return "bad"

        assert all(not isinstance(key, list) for key in catalog())

    def test_invalid_risk_level_rejected(self):
        with pytest.raises(ValueError, match="risk_level"):
            @tool("bad_risk", "Bad", {}, risk_level="writee")
            def bad_risk() -> str:
                return "bad"

        assert lookup("bad_risk") is None

    def test_non_string_risk_level_rejected_without_type_error(self):
        with pytest.raises(ValueError, match="risk_level"):
            @tool("bad_risk_type", "Bad", {}, risk_level=["write"])
            def bad_risk_type() -> str:
                return "bad"

        assert lookup("bad_risk_type") is None

    def test_non_object_parameters_rejected_without_catalog_mutation(self):
        with pytest.raises(ValueError, match="parameters"):
            @tool("bad_parameters", "Bad", [])
            def bad_parameters() -> str:
                return "bad"

        assert lookup("bad_parameters") is None

    def test_readonly_requires_read_risk(self):
        with pytest.raises(ValueError, match="readonly"):
            @tool("bad_readonly", "Bad", {}, readonly=True, risk_level="write")
            def bad_readonly() -> str:
                return "bad"

        assert lookup("bad_readonly") is None


# ═══════════════════════════════════════════════════════════
# 2.3 catalog / lookup / schemas
# ═══════════════════════════════════════════════════════════

class TestCatalogLookupSchemas:
    def test_catalog_returns_copy(self):
        _register_echo()
        c = catalog()
        c.pop("echo")
        assert "echo" in catalog()  # 内部不受影响

    def test_lookup_found(self):
        _register_echo()
        assert lookup("echo") is not None

    def test_lookup_not_found(self):
        assert lookup("nonexistent") is None

    def test_schemas_format(self):
        _register_echo()
        s = schemas()
        assert len(s) >= 1
        item = s[0]
        assert "name" in item
        assert "description" in item
        assert "parameters" in item

    def test_schemas_parameters_do_not_expose_catalog_mutation(self):
        @tool(
            "schema_isolated",
            "Schema isolated",
            {"type": "object", "properties": {"text": {"type": "string"}}},
        )
        def schema_isolated(text: str) -> str:
            return text

        schema = next(item for item in schemas() if item["name"] == "schema_isolated")
        schema["parameters"]["properties"]["text"]["type"] = "integer"

        spec = lookup("schema_isolated")
        assert spec is not None
        assert spec.parameters["properties"]["text"]["type"] == "string"

    def test_register_mcp_tools_adds_remote_tools_to_catalog(self):
        client = FakeMCPClient([
            MCPTool(
                name="search-docs",
                description="Search docs",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ])

        registered = tk.register_mcp_tools("docs", client)

        assert registered == ("mcp__docs__search_docs",)
        spec = lookup("mcp__docs__search_docs")
        assert spec is not None
        assert spec.readonly is True
        assert spec.risk_level == "read"
        assert spec.description == "MCP docs: Search docs"
        assert spec.parameters == {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }

    def test_mcp_tool_execution_routes_to_original_remote_tool_name(self):
        client = FakeMCPClient([
            MCPTool(
                name="search-docs",
                description="Search docs",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ], result={"content": [{"type": "text", "text": "found it"}]})
        tk.register_mcp_tools("docs", client)

        result = run_one("c1", "mcp__docs__search_docs", {"query": "ForgeAgent"})

        assert result.ok is True
        assert result.output == "found it"
        assert client.calls == [("search-docs", {"query": "ForgeAgent"})]

    def test_mcp_tool_execution_serializes_non_text_result(self):
        client = FakeMCPClient([
            MCPTool(name="stats", input_schema={"type": "object"}),
        ], result={"structuredContent": {"count": 2}})
        tk.register_mcp_tools("docs", client)

        result = run_one("c1", "mcp__docs__stats", {})

        assert result.ok is True
        assert result.output == '{"structuredContent":{"count":2}}'


# ═══════════════════════════════════════════════════════════
# 2.4 run_one
# ═══════════════════════════════════════════════════════════

class TestRunOne:
    def test_normal_execution(self):
        _register_echo()
        r = run_one("c1", "echo", {"text": "hello"})
        assert r.ok is True
        assert r.output == "echo: hello"
        assert r.call_id == "c1"
        assert r.name == "echo"

    def test_emits_before_and_after_tool_hooks(self):
        clear_hooks()
        _register_echo()
        seen: list[tuple[str, dict]] = []

        def capture(event: str, payload: dict) -> None:
            seen.append((event, payload))

        register_hook("tool.before", capture)
        register_hook("tool.after", capture)

        try:
            r = run_one("c1", "echo", {"text": "hello"})
        finally:
            clear_hooks()

        assert r.ok is True
        assert seen == [
            (
                "tool.before",
                {"call_id": "c1", "name": "echo", "args": {"text": "hello"}},
            ),
            (
                "tool.after",
                {
                    "call_id": "c1",
                    "name": "echo",
                    "ok": True,
                    "output": "echo: hello",
                },
            ),
        ]

    def test_non_string_call_id_gets_fallback(self):
        _register_echo()

        r = run_one(["bad"], "echo", {"text": "hello"})

        assert r.ok is True
        assert r.call_id == "call"

    def test_unknown_tool(self):
        r = run_one("c1", "no_such_tool", {})
        assert r.ok is False
        assert "Unknown" in r.output

    def test_non_string_tool_name_rejected(self):
        r = run_one("c1", ["bad"], {})

        assert r.ok is False
        assert "Invalid tool name" in r.output

    def test_non_object_args_rejected(self):
        _register_echo()

        r = run_one("c1", "echo", "not-json-object")

        assert r.ok is False
        assert "arguments must be an object" in r.output

    def test_missing_required_args_rejected_before_execution(self):
        _register_required()

        r = run_one("c1", "required_tool", {})

        assert r.ok is False
        assert "missing required argument" in r.output
        assert "path" in r.output

    def test_wrong_typed_args_rejected_before_execution(self):
        _register_typed()

        r = run_one("c1", "typed_tool", {"path": ["bad"]})

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "path" in r.output
        assert "string" in r.output

    def test_valid_typed_args_execute(self):
        _register_typed()

        r = run_one(
            "c1",
            "typed_tool",
            {
                "path": "note.md",
                "timeout": 10,
                "items": [],
                "options": {},
                "enabled": True,
                "mode": "slow",
            },
        )

        assert r.ok is True
        assert r.output == "typed-ok"

    def test_number_args_are_validated_before_execution(self):
        _register_number_tool()

        invalid = run_one("c1", "number_tool", {"ratio": "0.5"})
        valid_int = run_one("c2", "number_tool", {"ratio": 1})
        valid_float = run_one("c3", "number_tool", {"ratio": 0.5})

        assert invalid.ok is False
        assert "ratio" in invalid.output
        assert "number" in invalid.output
        assert valid_int.ok is True
        assert valid_int.output == "ratio: 1"
        assert valid_float.ok is True
        assert valid_float.output == "ratio: 0.5"

    def test_nullable_type_list_args_are_validated_before_execution(self):
        _register_nullable_tool()

        valid_null = run_one("c1", "nullable_tool", {"note": None})
        valid_string = run_one("c2", "nullable_tool", {"note": "hello"})
        invalid = run_one("c3", "nullable_tool", {"note": 123})

        assert valid_null.ok is True
        assert valid_null.output == "none"
        assert valid_string.ok is True
        assert valid_string.output == "note: hello"
        assert invalid.ok is False
        assert "note" in invalid.output
        assert "string" in invalid.output
        assert "null" in invalid.output

    def test_anyof_args_are_validated_before_execution(self):
        _register_anyof_tool()

        valid_string = run_one("c1", "anyof_tool", {"value": "hello"})
        valid_number = run_one("c2", "anyof_tool", {"value": 0.5})
        invalid = run_one("c3", "anyof_tool", {"value": {"bad": True}})

        assert valid_string.ok is True
        assert valid_string.output == "value: hello"
        assert valid_number.ok is True
        assert valid_number.output == "value: 0.5"
        assert invalid.ok is False
        assert "value" in invalid.output
        assert "anyOf" in invalid.output

    def test_oneof_args_are_validated_before_execution(self):
        _register_oneof_tool()

        valid_int = run_one("c1", "oneof_tool", {"value": 1})
        valid_bool = run_one("c2", "oneof_tool", {"value": True})
        invalid = run_one("c3", "oneof_tool", {"value": "true"})

        assert valid_int.ok is True
        assert valid_int.output == "value: 1"
        assert valid_bool.ok is True
        assert valid_bool.output == "value: True"
        assert invalid.ok is False
        assert "value" in invalid.output
        assert "oneOf" in invalid.output

    def test_allof_args_are_validated_before_execution(self):
        _register_allof_tool()

        valid = run_one("c1", "allof_tool", {"mode": "fast"})
        invalid_enum = run_one("c2", "allof_tool", {"mode": "turbo"})
        invalid_type = run_one("c3", "allof_tool", {"mode": 123})

        assert valid.ok is True
        assert valid.output == "mode: fast"
        assert invalid_enum.ok is False
        assert "mode" in invalid_enum.output
        assert "allOf" in invalid_enum.output
        assert invalid_type.ok is False
        assert "mode" in invalid_type.output
        assert "allOf" in invalid_type.output

    def test_not_args_are_validated_before_execution(self):
        _register_not_tool()

        valid = run_one("c1", "not_tool", {"mode": "safe"})
        invalid = run_one("c2", "not_tool", {"mode": "danger"})

        assert valid.ok is True
        assert valid.output == "mode: safe"
        assert invalid.ok is False
        assert "mode" in invalid.output
        assert "not" in invalid.output

    def test_string_length_args_are_validated_before_execution(self):
        _register_string_length_tool()

        valid = run_one("c1", "string_length_tool", {"label": "tool"})
        too_short = run_one("c2", "string_length_tool", {"label": "x"})
        too_long = run_one("c3", "string_length_tool", {"label": "tools"})

        assert valid.ok is True
        assert valid.output == "label: tool"
        assert too_short.ok is False
        assert "label" in too_short.output
        assert "at least 2" in too_short.output
        assert too_long.ok is False
        assert "label" in too_long.output
        assert "at most 4" in too_long.output

    def test_number_range_args_are_validated_before_execution(self):
        _register_number_range_tool()

        valid = run_one("c1", "number_range_tool", {"ratio": 0.5})
        too_small = run_one("c2", "number_range_tool", {"ratio": -0.1})
        too_large = run_one("c3", "number_range_tool", {"ratio": 1.1})

        assert valid.ok is True
        assert valid.output == "ratio: 0.5"
        assert too_small.ok is False
        assert "ratio" in too_small.output
        assert "at least 0" in too_small.output
        assert too_large.ok is False
        assert "ratio" in too_large.output
        assert "at most 1" in too_large.output

    def test_exclusive_number_range_args_are_validated_before_execution(self):
        _register_exclusive_number_range_tool()

        valid = run_one("c1", "exclusive_number_range_tool", {"ratio": 0.5})
        too_small = run_one("c2", "exclusive_number_range_tool", {"ratio": 0})
        too_large = run_one("c3", "exclusive_number_range_tool", {"ratio": 1})

        assert valid.ok is True
        assert valid.output == "ratio: 0.5"
        assert too_small.ok is False
        assert "ratio" in too_small.output
        assert "greater than 0" in too_small.output
        assert too_large.ok is False
        assert "ratio" in too_large.output
        assert "less than 1" in too_large.output

    def test_pattern_args_are_validated_before_execution(self):
        _register_pattern_tool()

        valid = run_one("c1", "pattern_tool", {"slug": "valid_slug1"})
        invalid = run_one("c2", "pattern_tool", {"slug": "Invalid-Slug"})

        assert valid.ok is True
        assert valid.output == "slug: valid_slug1"
        assert invalid.ok is False
        assert "slug" in invalid.output
        assert "pattern" in invalid.output

    def test_array_length_args_are_validated_before_execution(self):
        _register_array_length_tool()

        valid = run_one("c1", "array_length_tool", {"items": ["a", "b"]})
        too_few = run_one("c2", "array_length_tool", {"items": []})
        too_many = run_one("c3", "array_length_tool", {"items": ["a", "b", "c"]})

        assert valid.ok is True
        assert valid.output == "items: 2"
        assert too_few.ok is False
        assert "items" in too_few.output
        assert "at least 1" in too_few.output
        assert too_many.ok is False
        assert "items" in too_many.output
        assert "at most 2" in too_many.output

    def test_prefix_items_args_are_validated_before_execution(self):
        _register_prefix_items_tool()

        valid = run_one("c1", "prefix_items_tool", {"command": ["run", 3]})
        invalid_action = run_one("c2", "prefix_items_tool", {"command": ["ship", 3]})
        invalid_count = run_one("c3", "prefix_items_tool", {"command": ["run", 0]})
        extra = run_one("c4", "prefix_items_tool", {"command": ["run", 3, "extra"]})

        assert valid.ok is True
        assert valid.output == "command: run 3"
        assert invalid_action.ok is False
        assert "command[0]" in invalid_action.output
        assert "run" in invalid_action.output
        assert invalid_count.ok is False
        assert "command[1]" in invalid_count.output
        assert "at least 1" in invalid_count.output
        assert extra.ok is False
        assert "command[2]" in extra.output
        assert "additional" in extra.output

    def test_items_false_args_are_validated_before_execution(self):
        _register_empty_array_tool()

        valid = run_one("c1", "empty_array_tool", {"items": []})
        invalid = run_one("c2", "empty_array_tool", {"items": ["extra"]})

        assert valid.ok is True
        assert valid.output == "items: 0"
        assert invalid.ok is False
        assert "items[0]" in invalid.output
        assert "additional" in invalid.output

    def test_unique_items_args_are_validated_before_execution(self):
        _register_unique_items_tool()

        valid = run_one("c1", "unique_items_tool", {"tags": ["a", "b"]})
        duplicate = run_one("c2", "unique_items_tool", {"tags": ["a", "a"]})

        assert valid.ok is True
        assert valid.output == "tags: 2"
        assert duplicate.ok is False
        assert "tags" in duplicate.output
        assert "unique" in duplicate.output

    def test_unique_items_rejects_non_json_serializable_values(self):
        _register_unique_items_tool()

        r = run_one("c1", "unique_items_tool", {"tags": [object()]})

        assert r.ok is False
        assert "tags" in r.output
        assert "JSON-serializable" in r.output

    def test_contains_args_are_validated_before_execution(self):
        _register_contains_tool()

        valid = run_one("c1", "contains_tool", {"tags": ["secondary", "primary"]})
        missing = run_one("c2", "contains_tool", {"tags": ["secondary", "backup"]})

        assert valid.ok is True
        assert valid.output == "tags: 2"
        assert missing.ok is False
        assert "tags" in missing.output
        assert "matching item" in missing.output

    def test_contains_count_args_are_validated_before_execution(self):
        _register_contains_count_tool()

        valid = run_one(
            "c1",
            "contains_count_tool",
            {"tags": ["primary", "secondary", "primary"]},
        )
        too_few = run_one("c2", "contains_count_tool", {"tags": ["primary", "secondary"]})
        too_many = run_one(
            "c3",
            "contains_count_tool",
            {"tags": ["primary", "primary", "secondary", "primary", "primary"]},
        )

        assert valid.ok is True
        assert valid.output == "tags: 3"
        assert too_few.ok is False
        assert "tags" in too_few.output
        assert "at least 2 matching" in too_few.output
        assert too_many.ok is False
        assert "tags" in too_many.output
        assert "at most 3 matching" in too_many.output

    def test_const_args_are_validated_before_execution(self):
        _register_const_tool()

        valid = run_one("c1", "const_tool", {"version": "v1"})
        invalid = run_one("c2", "const_tool", {"version": "v2"})

        assert valid.ok is True
        assert valid.output == "version: v1"
        assert invalid.ok is False
        assert "version" in invalid.output
        assert "v1" in invalid.output

    def test_multiple_of_args_are_validated_before_execution(self):
        _register_multiple_of_tool()

        valid = run_one("c1", "multiple_of_tool", {"count": 10})
        invalid = run_one("c2", "multiple_of_tool", {"count": 12})

        assert valid.ok is True
        assert valid.output == "count: 10"
        assert invalid.ok is False
        assert "count" in invalid.output
        assert "multiple of 5" in invalid.output

    def test_unknown_args_rejected_before_execution(self):
        _register_typed()

        r = run_one("c1", "typed_tool", {"unexpected": "value"})

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "unexpected" in r.output

    def test_unknown_args_rejected_when_schema_has_no_properties(self):
        _register_readonly()

        r = run_one("c1", "reader", {"unexpected": "value"})

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "unexpected" in r.output

    def test_enum_args_rejected_before_execution(self):
        _register_typed()

        r = run_one("c1", "typed_tool", {"mode": "turbo"})

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "mode" in r.output
        assert "fast" in r.output

    def test_array_item_missing_required_args_rejected_before_execution(self):
        _register_nested()

        r = run_one(
            "c1",
            "nested_tool",
            {"agents": [{"description": "check"}]},
        )

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "agents[0].prompt" in r.output

    def test_nested_unknown_args_rejected_before_execution(self):
        _register_nested()

        r = run_one(
            "c1",
            "nested_tool",
            {
                "agents": [
                    {
                        "description": "check",
                        "prompt": "run tests",
                        "unexpected": "value",
                    }
                ]
            },
        )

        assert r.ok is False
        assert "Invalid arguments" in r.output
        assert "agents[0].unexpected" in r.output

    def test_additional_properties_object_args_execute(self):
        _register_object_map()

        r = run_one("c1", "object_map_tool", {"options": {"extra": "value"}})

        assert r.ok is True
        assert r.output == "options: 1"

    def test_additional_properties_schema_is_validated(self):
        _register_typed_object_map()

        invalid = run_one("c1", "typed_object_map_tool", {"labels": {"env": 123}})
        valid = run_one("c2", "typed_object_map_tool", {"labels": {"env": "prod"}})

        assert invalid.ok is False
        assert "labels.env" in invalid.output
        assert "string" in invalid.output
        assert valid.ok is True
        assert valid.output == "labels: 1"

    def test_object_size_args_are_validated_before_execution(self):
        _register_sized_object_map()

        valid = run_one("c1", "sized_object_map_tool", {"labels": {"env": "prod"}})
        too_few = run_one("c2", "sized_object_map_tool", {"labels": {}})
        too_many = run_one(
            "c3",
            "sized_object_map_tool",
            {"labels": {"env": "prod", "tier": "1", "team": "core"}},
        )

        assert valid.ok is True
        assert valid.output == "labels: 1"
        assert too_few.ok is False
        assert "labels" in too_few.output
        assert "at least 1" in too_few.output
        assert too_many.ok is False
        assert "labels" in too_many.output
        assert "at most 2" in too_many.output

    def test_object_property_names_are_validated_before_execution(self):
        _register_named_object_map()

        valid = run_one("c1", "named_object_map_tool", {"labels": {"env_1": "prod"}})
        invalid = run_one("c2", "named_object_map_tool", {"labels": {"Invalid-Key": "prod"}})

        assert valid.ok is True
        assert valid.output == "labels: 1"
        assert invalid.ok is False
        assert "labels.Invalid-Key" in invalid.output
        assert "pattern" in invalid.output

    def test_pattern_properties_are_validated_before_execution(self):
        _register_patterned_object_map()

        valid = run_one(
            "c1",
            "patterned_object_map_tool",
            {"labels": {"num_retries": 3, "str_env": "prod", "misc": False}},
        )
        invalid = run_one(
            "c2",
            "patterned_object_map_tool",
            {"labels": {"num_retries": "three"}},
        )

        assert valid.ok is True
        assert valid.output == "labels: 3"
        assert invalid.ok is False
        assert "labels.num_retries" in invalid.output
        assert "integer" in invalid.output

    def test_pattern_properties_satisfy_additional_properties_false(self):
        _register_strict_patterned_object_map()

        valid = run_one(
            "c1",
            "strict_patterned_object_map_tool",
            {"labels": {"num_retries": 3, "str_env": "prod"}},
        )
        unknown = run_one(
            "c2",
            "strict_patterned_object_map_tool",
            {"labels": {"misc": "prod"}},
        )

        assert valid.ok is True
        assert valid.output == "labels: 2"
        assert unknown.ok is False
        assert "labels.misc" in unknown.output
        assert "unknown" in unknown.output

    def test_root_additional_properties_schema_is_validated(self):
        _register_freeform_root()

        invalid = run_one("c1", "freeform_root_tool", {"env": 123})
        valid = run_one("c2", "freeform_root_tool", {"env": "prod"})

        assert invalid.ok is False
        assert "env" in invalid.output
        assert "string" in invalid.output
        assert valid.ok is True
        assert valid.output == "root: 1"

    def test_root_pattern_properties_satisfy_additional_properties_false(self):
        _register_strict_patterned_root()

        valid = run_one("c1", "strict_patterned_root_tool", {"env_name": "prod"})
        unknown = run_one("c2", "strict_patterned_root_tool", {"name": "prod"})

        assert valid.ok is True
        assert valid.output == "root: 1"
        assert unknown.ok is False
        assert "name" in unknown.output
        assert "unknown" in unknown.output

    def test_dependent_required_args_are_validated_before_execution(self):
        _register_dependent_required_tool()

        valid_pair = run_one(
            "c1",
            "dependent_required_tool",
            {"username": "alice", "password": "secret"},
        )
        valid_independent = run_one("c2", "dependent_required_tool", {"token": "t"})
        missing = run_one("c3", "dependent_required_tool", {"username": "alice"})

        assert valid_pair.ok is True
        assert valid_pair.output == "auth: True False"
        assert valid_independent.ok is True
        assert valid_independent.output == "auth: False True"
        assert missing.ok is False
        assert "username" in missing.output
        assert "password" in missing.output

    def test_dependent_schema_args_are_validated_before_execution(self):
        _register_dependent_schema_tool()

        valid = run_one(
            "c1",
            "dependent_schema_tool",
            {"create": True, "path": "note.md", "mode": "file"},
        )
        missing_path = run_one("c2", "dependent_schema_tool", {"create": True, "mode": "file"})
        invalid_mode = run_one(
            "c3",
            "dependent_schema_tool",
            {"create": True, "path": "note.md", "mode": "pipe"},
        )

        assert valid.ok is True
        assert valid.output == "create: True note.md file"
        assert missing_path.ok is False
        assert "path" in missing_path.output
        assert invalid_mode.ok is False
        assert "mode" in invalid_mode.output
        assert "file" in invalid_mode.output

    def test_conditional_schema_args_are_validated_before_execution(self):
        _register_conditional_schema_tool()

        valid_delete = run_one(
            "c1",
            "conditional_schema_tool",
            {"action": "delete", "force": True},
        )
        valid_write = run_one(
            "c2",
            "conditional_schema_tool",
            {"action": "write", "path": "note.md"},
        )
        missing_force = run_one("c3", "conditional_schema_tool", {"action": "delete"})
        missing_path = run_one("c4", "conditional_schema_tool", {"action": "write"})

        assert valid_delete.ok is True
        assert valid_delete.output == "delete:  True"
        assert valid_write.ok is True
        assert valid_write.output == "write: note.md False"
        assert missing_force.ok is False
        assert "then" in missing_force.output
        assert "force" in missing_force.output
        assert missing_path.ok is False
        assert "else" in missing_path.output
        assert "path" in missing_path.output

    def test_object_subschemas_allow_additional_properties_by_default(self):
        _register_conditional_default_additional_tool()

        valid_write = run_one(
            "c1",
            "conditional_default_additional_tool",
            {"action": "write", "path": "note.md"},
        )
        invalid_delete = run_one(
            "c2",
            "conditional_default_additional_tool",
            {"action": "delete", "force": False},
        )

        assert valid_write.ok is True
        assert valid_write.output == "write: note.md False"
        assert invalid_delete.ok is False
        assert "then" in invalid_delete.output
        assert "force" in invalid_delete.output

    def test_valid_array_items_execute(self):
        _register_nested()

        r = run_one(
            "c1",
            "nested_tool",
            {
                "agents": [
                    {
                        "description": "check",
                        "prompt": "run tests",
                        "type": "verification",
                    }
                ]
            },
        )

        assert r.ok is True
        assert r.output == "nested: 1"

    def test_exception_caught(self):
        _register_failing()
        r = run_one("c1", "fail_tool", {})
        assert r.ok is False
        assert "boom" in r.output

    def test_permission_denied(self):
        _register_echo()
        enforcer = MagicMock()
        enforcer.check.return_value = "DENIED — test reason"
        set_enforcer(enforcer)
        r = run_one("c1", "echo", {"text": "hi"})
        assert r.ok is False
        assert "DENIED" in r.output

    def test_permission_check_exception_returns_error_without_execution(self):
        executed: list[str] = []

        @tool("guarded_tool", "Guarded", {})
        def guarded_tool() -> str:
            executed.append("ran")
            return "ok"

        enforcer = MagicMock()
        enforcer.check.side_effect = RuntimeError("permission backend down")
        set_enforcer(enforcer)

        r = run_one("c1", "guarded_tool", {})

        assert r.ok is False
        assert "Permission check failed" in r.output
        assert "permission backend down" in r.output
        assert executed == []

    def test_permission_allowed(self):
        _register_echo()
        enforcer = MagicMock()
        enforcer.check.return_value = None  # 允许
        set_enforcer(enforcer)
        r = run_one("c1", "echo", {"text": "hi"})
        assert r.ok is True


# ═══════════════════════════════════════════════════════════
# 2.5 run_batch
# ═══════════════════════════════════════════════════════════

class TestRunBatch:
    def test_empty_list(self):
        assert run_batch([]) == []

    def test_non_list_calls_returns_error_result(self):
        results = run_batch("not-a-call-list")

        assert len(results) == 1
        assert results[0].ok is False
        assert "calls must be a list" in results[0].output

    def test_order_preserved(self):
        @tool("a", "A", {}, readonly=True, risk_level="read")
        def tool_a() -> str:
            return "a"

        @tool("b", "B", {}, readonly=True, risk_level="read")
        def tool_b() -> str:
            return "b"

        results = run_batch([("c1", "a", {}), ("c2", "b", {})])
        assert len(results) == 2
        assert results[0].output == "a"
        assert results[1].output == "b"

    def test_all_readonly_concurrent(self):
        """全部只读工具应并发执行。"""
        executed_threads: list[str] = []

        @tool("r1", "R1", {}, readonly=True, risk_level="read")
        def r1() -> str:
            executed_threads.append(threading.current_thread().name)
            return "r1"

        @tool("r2", "R2", {}, readonly=True, risk_level="read")
        def r2() -> str:
            executed_threads.append(threading.current_thread().name)
            return "r2"

        results = run_batch([("c1", "r1", {}), ("c2", "r2", {})])
        assert all(r.ok for r in results)
        # 线程池使用非主线程
        assert len(executed_threads) == 2

    def test_mixed_readwrite_sequential(self):
        """混合读写应顺序执行。"""
        _register_readonly()
        _register_echo()

        results = run_batch([
            ("c1", "reader", {}),
            ("c2", "echo", {"text": "hi"}),
        ])
        assert len(results) == 2
        assert results[0].ok is True
        assert results[1].ok is True

    def test_single_readonly_sequential(self):
        """单个只读调用走顺序路径。"""
        _register_readonly()
        results = run_batch([("c1", "reader", {})])
        assert len(results) == 1
        assert results[0].ok is True

    def test_malformed_call_shape_returns_error_result(self):
        results = run_batch([("c1", "reader")])

        assert len(results) == 1
        assert results[0].ok is False
        assert "Invalid tool call" in results[0].output

    def test_malformed_call_args_returns_error_result(self):
        _register_echo()

        results = run_batch([("c1", "echo", "bad-args")])

        assert len(results) == 1
        assert results[0].ok is False
        assert "arguments must be an object" in results[0].output

    def test_malformed_call_name_returns_error_result(self):
        results = run_batch([("c1", ["bad"], {})])

        assert len(results) == 1
        assert results[0].ok is False
        assert "Invalid tool name" in results[0].output

    def test_malformed_call_id_gets_indexed_fallback(self):
        _register_echo()

        results = run_batch([(["bad"], "echo", {"text": "hello"})])

        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].call_id == "call_0"

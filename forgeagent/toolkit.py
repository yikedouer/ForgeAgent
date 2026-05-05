"""工具注册表 — 装饰器驱动的工具管理。

每个工具都是用 @tool() 装饰的普通函数。装饰器收集
元数据（名称、描述、参数 schema）并注册到全局目录中。
Engine 在运行时查询该目录来构建 LLM 的工具声明并分发调用。

刻意不使用类 — 工具就是附带元数据的函数，更贴近原始架构的
声明式风格。
"""

from __future__ import annotations

import concurrent.futures
import copy
import logging
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from .toolkit_mcp import build_mcp_tool_specs
from .toolkit_schema import arg_type_error

if TYPE_CHECKING:
    from .core.permissions import PermissionEnforcer

log = logging.getLogger(__name__)

_VALID_RISK_LEVELS = {"read", "write", "danger"}


# ── 工具描述符 ───────────────────────────────────────

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON-Schema 片段
    handler: Callable[..., str]    # 实际执行函数
    readonly: bool = False    # 是否可并发执行
    risk_level: str = "write" # 'read' / 'write' / 'danger'


# ── 全局工具目录 ───────────────────────────────────────

_CATALOG: dict[str, ToolSpec] = {}


def register_mcp_tools(server_name: str, client: object) -> tuple[str, ...]:
    """Expose tools from an initialized MCP client through the ForgeAgent catalog."""
    registered: list[str] = []
    for mcp_spec in build_mcp_tool_specs(server_name, client):
        _CATALOG[mcp_spec.name] = ToolSpec(
            name=mcp_spec.name,
            description=mcp_spec.description,
            parameters=mcp_spec.parameters,
            handler=mcp_spec.handler,
            readonly=mcp_spec.readonly,
            risk_level=mcp_spec.risk_level,
        )
        registered.append(mcp_spec.name)
    return tuple(registered)


def tool(
    name: str,
    description: str,
    parameters: dict,
    *,
    readonly: bool = False,
    risk_level: str = "write",
) -> Callable:
    """装饰器：将函数注册为工具。"""
    if not isinstance(name, str) or not name:
        raise ValueError("invalid tool name: expected non-empty string")
    if not isinstance(parameters, dict):
        raise ValueError("invalid tool parameters: expected object schema")
    if not isinstance(risk_level, str) or risk_level not in _VALID_RISK_LEVELS:
        allowed = ", ".join(sorted(_VALID_RISK_LEVELS))
        raise ValueError(f"invalid risk_level '{risk_level}' for tool '{name}'; expected: {allowed}")
    if readonly and risk_level != "read":
        raise ValueError(
            f"invalid readonly tool '{name}': readonly tools must use risk_level 'read'"
        )

    def decorator(handler: Callable[..., str]) -> Callable[..., str]:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            readonly=readonly,
            risk_level=risk_level,
        )
        _CATALOG[name] = spec
        log.debug("工具注册: %s  risk=%s  readonly=%s", name, risk_level, readonly)
        return handler
    return decorator


def catalog() -> dict[str, ToolSpec]:
    """返回完整的工具目录（只读副本）。"""
    return dict(_CATALOG)


def lookup(name: str) -> ToolSpec | None:
    return _CATALOG.get(name)


def schemas() -> list[dict]:
    """构建 LLM 需要的函数 schema 列表。"""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": copy.deepcopy(spec.parameters),
        }
        for spec in _CATALOG.values()
    ]


# ── 权限执行器（由 Engine 启动时设置）────────────────

_enforcer: PermissionEnforcer | None = None


def set_enforcer(enforcer: PermissionEnforcer) -> None:
    global _enforcer
    _enforcer = enforcer


def _emit_hook(event: str, payload: dict) -> None:
    """Emit runtime hooks lazily to avoid import-time core/toolkit cycles."""
    from .core.hooks import emit_hook

    emit_hook(event, payload)


# ── 执行辅助 ───────────────────────────────────────────

@dataclass
class ToolResult:
    call_id: str
    name: str
    output: str
    ok: bool = True


def _string_id(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def run_one(call_id: str, name: str, args: dict) -> ToolResult:
    """按名称执行单个工具。"""
    call_id = _string_id(call_id, "call")
    if not isinstance(name, str) or not name:
        return ToolResult(
            call_id=call_id,
            name="",
            output="Invalid tool name: expected non-empty string",
            ok=False,
        )
    spec = lookup(name)
    if spec is None:
        return ToolResult(call_id=call_id, name=name,
                                output=f"Unknown tool: {name}", ok=False)
    if not isinstance(args, dict):
        return ToolResult(
            call_id=call_id,
            name=name,
            output=f"Invalid arguments for {name}: arguments must be an object",
            ok=False,
        )
    missing = [
        key for key in spec.parameters.get("required", [])
        if isinstance(key, str) and key not in args
    ]
    if missing:
        names = ", ".join(missing)
        return ToolResult(
            call_id=call_id,
            name=name,
            output=f"Invalid arguments for {name}: missing required argument(s): {names}",
            ok=False,
        )
    type_error = arg_type_error(spec.parameters, args)
    if type_error:
        return ToolResult(
            call_id=call_id,
            name=name,
            output=f"Invalid arguments for {name}: {type_error}",
            ok=False,
        )

    # 权限检查
    if _enforcer is not None:
        try:
            denial = _enforcer.check(name, spec.risk_level, args)
        except Exception as exc:
            log.error("权限检查异常: %s — %s", name, exc)
            return ToolResult(
                call_id=call_id,
                name=name,
                output=f"Permission check failed: {exc}",
                ok=False,
            )
        if denial:
            log.warning("工具被拒绝: %s — %s", name, denial)
            return ToolResult(call_id=call_id, name=name,
                                    output=denial, ok=False)

    _emit_hook("tool.before", {"call_id": call_id, "name": name, "args": args})
    try:
        output = spec.handler(**args)
        result = ToolResult(call_id=call_id, name=name, output=output)
    except Exception as exc:
        log.error("工具执行异常: %s — %s", name, exc)
        result = ToolResult(call_id=call_id, name=name,
                                  output=f"Error: {exc}", ok=False)
    _emit_hook(
        "tool.after",
        {
            "call_id": result.call_id,
            "name": result.name,
            "ok": result.ok,
            "output": result.output,
        },
    )
    return result


def run_batch(calls: list[tuple[str, str, dict]]) -> list[ToolResult]:
    """批量执行工具调用，只读工具可并行执行。

    每个元素为 (call_id, tool_name, args)。
    保持输入列表的顺序。
    """
    if not isinstance(calls, list):
        return [ToolResult(
            call_id="call",
            name="",
            output="Invalid tool calls: calls must be a list",
            ok=False,
        )]
    if not calls:
        return []

    normalized: list[tuple[str, str, dict] | ToolResult] = []
    for i, call in enumerate(calls):
        if not isinstance(call, tuple) or len(call) != 3:
            normalized.append(ToolResult(
                call_id=f"call_{i}",
                name="",
                output="Invalid tool call: expected (call_id, name, args)",
                ok=False,
            ))
            continue
        if not isinstance(call[1], str) or not call[1]:
            normalized.append(ToolResult(
                call_id=_string_id(call[0], f"call_{i}"),
                name="",
                output="Invalid tool name: expected non-empty string",
                ok=False,
            ))
            continue
        normalized.append((_string_id(call[0], f"call_{i}"), call[1], call[2]))

    valid_calls = [call for call in normalized if isinstance(call, tuple)]

    # 如果全部是只读调用，并发执行
    all_readonly = all(
        (s := lookup(name)) is not None and s.readonly
        for _, name, _ in valid_calls
    )

    if all_readonly and len(valid_calls) > 1 and len(valid_calls) == len(normalized):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(valid_calls)) as pool:
            futures = {
                pool.submit(run_one, cid, name, args): i
                for i, (cid, name, args) in enumerate(valid_calls)
            }
            results = [None] * len(valid_calls)
            for fut in concurrent.futures.as_completed(futures):
                results[futures[fut]] = fut.result()
            return results  # type: ignore[return-value]

    # 否则顺序执行（写操作不可重叠）
    results: list[ToolResult] = []
    for call in normalized:
        if isinstance(call, ToolResult):
            results.append(call)
            continue
        cid, name, args = call
        results.append(run_one(cid, name, args))
    return results

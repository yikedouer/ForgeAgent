from __future__ import annotations

from dataclasses import dataclass

from forgecc.core.engine_loop import (
    build_tool_calls,
    notify_tool_callbacks,
    split_plan_tool_calls,
)


@dataclass
class Invocation:
    call_id: str
    fn_name: object
    fn_args: object


def test_build_tool_calls_extracts_provider_invocations():
    invocations = [
        Invocation("call-1", "read_file", {"path": "a.py"}),
        Invocation("call-2", "write_file", {"path": "b.py"}),
    ]

    assert build_tool_calls(invocations) == [
        ("call-1", "read_file", {"path": "a.py"}),
        ("call-2", "write_file", {"path": "b.py"}),
    ]


def test_split_plan_tool_calls_keeps_order_with_non_string_names_as_normal():
    calls = [
        ("call-1", "read_file", {}),
        ("call-2", "enter_plan_mode", {}),
        ("call-3", 123, {}),
        ("call-4", "exit_plan_mode", {}),
    ]

    plan_calls, normal_calls = split_plan_tool_calls(
        calls,
        plan_tool_names={"enter_plan_mode", "exit_plan_mode"},
    )

    assert plan_calls == [
        ("call-2", "enter_plan_mode", {}),
        ("call-4", "exit_plan_mode", {}),
    ]
    assert normal_calls == [
        ("call-1", "read_file", {}),
        ("call-3", 123, {}),
    ]


def test_notify_tool_callbacks_suppresses_callback_errors():
    warnings = []
    seen = []
    invocations = [
        Invocation("call-1", "read_file", {"path": "a.py"}),
        Invocation("call-2", "write_file", {"path": "b.py"}),
    ]

    def callback(name, args):
        seen.append((name, args))
        if name == "read_file":
            raise RuntimeError("callback failed")

    notify_tool_callbacks(invocations, callback, warn=warnings.append)

    assert seen == [
        ("read_file", {"path": "a.py"}),
        ("write_file", {"path": "b.py"}),
    ]
    assert warnings == ["工具回调异常: callback failed"]

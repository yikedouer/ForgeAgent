from __future__ import annotations

from forgecc.core.engine_loop import append_plan_tool_results


def test_append_plan_tool_results_executes_tools_and_appends_messages():
    calls = [
        ("call-1", "enter_plan_mode", {}),
        ("call-2", "exit_plan_mode", {}),
    ]
    executed = []
    appended = []

    append_plan_tool_results(
        calls,
        execute_plan_tool=lambda name: executed.append(name) or f"ran {name}",
        append_message=appended.append,
    )

    assert executed == ["enter_plan_mode", "exit_plan_mode"]
    assert appended == [
        {"role": "tool", "tool_call_id": "call-1", "content": "ran enter_plan_mode"},
        {"role": "tool", "tool_call_id": "call-2", "content": "ran exit_plan_mode"},
    ]


def test_append_plan_tool_results_uses_fallback_for_blank_call_ids():
    appended = []

    append_plan_tool_results(
        [("", "enter_plan_mode", {})],
        execute_plan_tool=lambda name: "ok",
        append_message=appended.append,
    )

    assert appended == [
        {"role": "tool", "tool_call_id": "call_0", "content": "ok"},
    ]

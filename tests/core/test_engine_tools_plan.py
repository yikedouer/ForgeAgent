from __future__ import annotations

from forgeagent.core.engine_loop import append_plan_tool_results


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


def test_append_plan_tool_results_emits_events():
    events = []

    append_plan_tool_results(
        [("call-1", "exit_plan_mode", {})],
        execute_plan_tool=lambda name: f"ran {name}",
        append_message=lambda _message: None,
        on_event=lambda kind, payload: events.append((kind, payload)),
    )

    assert events == [
        (
            "plan_tool_result",
            {
                "call_id": "call-1",
                "name": "exit_plan_mode",
                "output_chars": 18,
                "preview": "ran exit_plan_mode",
            },
        )
    ]

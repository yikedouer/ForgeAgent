from __future__ import annotations

from types import SimpleNamespace

from forgeagent.core.engine_loop import prepare_round_inputs


def test_prepare_round_inputs_compacts_builds_messages_injects_memory_and_selects_schemas():
    collapse = object()
    state = SimpleNamespace(
        transcript=[{"role": "user", "content": "hi"}],
        settings=SimpleNamespace(context_budget=100),
        provider=object(),
        session_id="session-1",
        _collapse=None,
        _autocompact_failures=[0],
        _last_input_tokens=42,
        _last_api_call_time=12.3,
        _custom_system_prompt="custom",
        _plan=SimpleNamespace(plan_file_path="/tmp/plan.md"),
        _custom_tool_names={"read_file"},
    )
    calls = {}

    def maybe_compact_fn(*args, **kwargs):
        calls["compact"] = (args, kwargs)
        return SimpleNamespace(collapse=collapse)

    def directive_builder(**kwargs):
        calls["directive"] = kwargs
        return "directive"

    def wire_builder(**kwargs):
        calls["wire"] = kwargs
        return [{"role": "system", "content": kwargs["directive"]}]

    def schema_selector(*args, **kwargs):
        calls["schemas"] = (args, kwargs)
        return [{"name": "read_file"}]

    result = prepare_round_inputs(
        state,
        plan_prompt_builder=lambda *args, **kwargs: "plan prompt",
        plan_tool_defs=[{"name": "enter_plan_mode"}],
        toolkit_schemas=[{"name": "read_file"}, {"name": "write_file"}],
        maybe_compact_fn=maybe_compact_fn,
        directive_builder=directive_builder,
        wire_builder=wire_builder,
        memory_injector=lambda messages: [*messages, {"role": "user", "content": "mem"}],
        schema_selector=schema_selector,
    )

    assert state._collapse is collapse
    assert calls["compact"][0] == (state.transcript, 100, state.provider)
    assert calls["compact"][1] == {
        "session_id": "session-1",
        "collapse_state": None,
        "failure_count": [0],
        "last_input_tokens": 42,
        "last_api_call_time": 12.3,
    }
    assert calls["directive"]["custom_system_prompt"] == "custom"
    assert calls["directive"]["plan_file_path"] == "/tmp/plan.md"
    assert calls["wire"] == {
        "directive": "directive",
        "transcript": state.transcript,
        "collapse": collapse,
    }
    assert calls["schemas"] == (
        ([{"name": "read_file"}, {"name": "write_file"}],),
        {
            "custom_tool_names": {"read_file"},
            "plan_tool_defs": [{"name": "enter_plan_mode"}],
        },
    )
    assert result.directive == "directive"
    assert result.wire_messages == [
        {"role": "system", "content": "directive"},
        {"role": "user", "content": "mem"},
    ]
    assert result.tool_schemas == [{"name": "read_file"}]


def test_prepare_round_inputs_keeps_existing_collapse_when_compaction_has_no_new_collapse():
    existing = object()
    state = SimpleNamespace(
        transcript=[],
        settings=SimpleNamespace(context_budget=100),
        provider=object(),
        session_id="session-1",
        _collapse=existing,
        _autocompact_failures=[0],
        _last_input_tokens=0,
        _last_api_call_time=None,
        _custom_system_prompt=None,
        _plan=SimpleNamespace(plan_file_path=None),
        _custom_tool_names=None,
    )

    prepare_round_inputs(
        state,
        plan_prompt_builder=lambda *args, **kwargs: "plan prompt",
        plan_tool_defs=[],
        toolkit_schemas=[],
        maybe_compact_fn=lambda *args, **kwargs: SimpleNamespace(collapse=None),
        directive_builder=lambda **kwargs: "directive",
        wire_builder=lambda **kwargs: [],
        memory_injector=lambda messages: messages,
        schema_selector=lambda *args, **kwargs: [],
    )

    assert state._collapse is existing

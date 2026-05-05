from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from forgecc.core.engine_loop import run_agent_loop
from forgecc.core.permissions import PermissionMode


def _completion(text: str, invocations: list | None = None) -> MagicMock:
    comp = MagicMock()
    comp.text = text
    comp.invocations = invocations or []
    comp.usage_in = 3
    comp.usage_out = 2
    comp.raw_assistant_msg = {"role": "assistant", "content": text}
    return comp


def test_run_agent_loop_returns_text_and_autosaves():
    state = SimpleNamespace(
        settings=SimpleNamespace(max_rounds=3, workspace="/tmp/workspace"),
        provider=object(),
        transcript=[],
        session_id="session-1",
        _round=0,
        _pending_prefetch="prefetch",
        _is_sub_agent=False,
        _collapse=None,
        _already_surfaced=set(),
        _session_memory_bytes=0,
        enforcer=SimpleNamespace(mode=PermissionMode.DANGER),
        _plan_file_path=None,
        _execute_plan_tool=lambda name: f"plan:{name}",
        _filter_plan_mode_calls=lambda calls: calls,
    )
    appended: list[dict] = []
    autosaves: list[bool] = []
    completed = _completion("done")

    def append_message(message: dict) -> None:
        appended.append(message)
        state.transcript.append(message)

    result = run_agent_loop(
        state,
        user_input="hi",
        on_token=None,
        on_instrument=None,
        append_message=append_message,
        autosave_checkpoint=lambda: autosaves.append(True),
        maybe_start_memory_prefetch_fn=lambda **kwargs: "prefetched",
        prepare_round_inputs_fn=lambda *args, **kwargs: SimpleNamespace(
            wire_messages=[{"role": "user", "content": "hi"}],
            tool_schemas=[],
            directive="system",
        ),
        generate_with_context_recovery_fn=lambda **kwargs: SimpleNamespace(
            completion=completed,
            collapse_reset=False,
        ),
        record_completion_usage_fn=lambda *args, **kwargs: SimpleNamespace(
            input_tokens=3,
            output_tokens=2,
            text_chars=4,
            invocation_count=0,
        ),
        build_tool_calls_fn=lambda invocations: [],
        notify_instrument_callbacks_fn=lambda *args, **kwargs: None,
        split_plan_tool_calls_fn=lambda calls, **kwargs: ([], []),
        append_plan_tool_results_fn=lambda *args, **kwargs: None,
        execute_normal_tool_calls_fn=lambda **kwargs: None,
        toolkit_schemas_fn=lambda: [],
        toolkit_run_batch_fn=lambda calls: [],
        persist_fn=lambda *args: "",
        memory_injector=lambda messages: messages,
        plan_prompt_builder=lambda *args, **kwargs: "",
        plan_tool_defs=[],
        plan_tool_names=set(),
        logger=MagicMock(),
        now=lambda: 123.0,
    )

    assert result == "done"
    assert state._pending_prefetch == "prefetched"
    assert state._round == 1
    assert appended == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "done"},
    ]
    assert autosaves == [True]

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from forgecc.core import engine_loop
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


def test_run_agent_loop_returns_text_and_autosaves(monkeypatch):
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

    state._append_message = append_message
    state._autosave_checkpoint = lambda: autosaves.append(True)
    state._inject_recalled_memories = lambda messages: messages

    monkeypatch.setattr(engine_loop, "maybe_start_memory_prefetch", lambda **kwargs: "prefetched")
    monkeypatch.setattr(
        engine_loop,
        "prepare_round_inputs",
        lambda *args, **kwargs: SimpleNamespace(
            wire_messages=[{"role": "user", "content": "hi"}],
            tool_schemas=[],
            directive="system",
        ),
    )
    monkeypatch.setattr(
        engine_loop,
        "generate_with_context_recovery",
        lambda **kwargs: SimpleNamespace(completion=completed, collapse_reset=False),
    )
    monkeypatch.setattr(
        engine_loop,
        "record_completion_usage",
        lambda *args, **kwargs: SimpleNamespace(
            input_tokens=3,
            output_tokens=2,
            text_chars=4,
            invocation_count=0,
        ),
    )
    monkeypatch.setattr(engine_loop, "build_tool_calls", lambda invocations: [])
    monkeypatch.setattr(engine_loop, "notify_instrument_callbacks", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_loop, "split_plan_tool_calls", lambda calls, **kwargs: ([], []))
    monkeypatch.setattr(engine_loop, "append_plan_tool_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_loop, "execute_normal_tool_calls", lambda **kwargs: None)
    monkeypatch.setattr(engine_loop.toolkit, "schemas", lambda: [])
    monkeypatch.setattr(engine_loop.toolkit, "run_batch", lambda calls: [])
    monkeypatch.setattr(engine_loop, "persist_if_large", lambda *args: "")
    monkeypatch.setattr(engine_loop, "build_plan_mode_prompt", lambda *args, **kwargs: "")

    result = run_agent_loop(
        state,
        user_input="hi",
        on_token=None,
        on_instrument=None,
    )

    assert result == "done"
    assert state._pending_prefetch == "prefetched"
    assert state._round == 1
    assert appended == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "done"},
    ]
    assert autosaves == [True]

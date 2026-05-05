from __future__ import annotations

from types import SimpleNamespace

from forgeagent.core.engine_session import reset_conversation_state


def test_reset_conversation_state_clears_transcript_and_runtime_fields():
    state = SimpleNamespace(
        transcript=[{"role": "user", "content": "hi"}],
        _round=4,
        _collapse=object(),
        _autocompact_failures=[3],
        _last_input_tokens=99,
        _last_api_call_time=123.4,
        _already_surfaced={"memory.md"},
        _session_memory_bytes=512,
        _pending_prefetch=object(),
        _plan=SimpleNamespace(context_cleared=True),
    )
    reset_calls = []

    reset_conversation_state(
        state,
        reset_persisted_tracking=lambda: reset_calls.append("reset"),
    )

    assert state.transcript == []
    assert state._round == 0
    assert state._collapse is None
    assert state._autocompact_failures == [0]
    assert state._last_input_tokens == 0
    assert state._last_api_call_time is None
    assert state._already_surfaced == set()
    assert state._session_memory_bytes == 0
    assert state._pending_prefetch is None
    assert state._plan.context_cleared is False
    assert reset_calls == ["reset"]

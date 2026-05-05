from __future__ import annotations

from types import SimpleNamespace

from forgecc.core.engine_loop import record_completion_usage


def test_record_completion_usage_updates_counters_and_returns_log_fields():
    state = SimpleNamespace(
        _last_input_tokens=0,
        _last_api_call_time=None,
        _total_input_tokens=10,
        _total_output_tokens=5,
    )
    completion = SimpleNamespace(
        usage_in=7,
        usage_out=3,
        text="hello",
        invocations=[object(), object()],
    )

    report = record_completion_usage(state, completion, now=123.4)

    assert state._last_input_tokens == 7
    assert state._last_api_call_time == 123.4
    assert state._total_input_tokens == 17
    assert state._total_output_tokens == 8
    assert report.input_tokens == 7
    assert report.output_tokens == 3
    assert report.text_chars == 5
    assert report.invocation_count == 2

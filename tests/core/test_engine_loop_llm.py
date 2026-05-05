from __future__ import annotations

import pytest

from forgeagent.core.engine_loop import generate_with_context_recovery
from forgeagent.core.errors import ContextWindowError


class Provider:
    def __init__(self, *, side_effect):
        self.side_effect = list(side_effect)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        next_result = self.side_effect.pop(0)
        if isinstance(next_result, Exception):
            raise next_result
        return next_result


def test_generate_with_context_recovery_returns_first_success_without_pruning():
    completion = object()
    provider = Provider(side_effect=[completion])
    pruned = []
    on_token = lambda token: token

    result = generate_with_context_recovery(
        provider=provider,
        wire_messages=[{"role": "system", "content": "sys"}],
        tool_schemas=[{"name": "read_file"}],
        on_token=on_token,
        directive="sys",
        transcript=[{"role": "user", "content": "hi"}],
        prune=lambda *args, **kwargs: pruned.append((args, kwargs)),
    )

    assert result.completion is completion
    assert result.collapse_reset is False
    assert pruned == []
    assert provider.calls == [{
        "messages": [{"role": "system", "content": "sys"}],
        "tool_schemas": [{"name": "read_file"}],
        "on_token": on_token,
    }]


def test_generate_with_context_recovery_prunes_and_retries_after_context_error():
    completion = object()
    provider = Provider(side_effect=[ContextWindowError("too large"), completion])
    transcript = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "reply"},
    ]
    pruned = []

    result = generate_with_context_recovery(
        provider=provider,
        wire_messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "projected"}],
        tool_schemas=[],
        on_token=None,
        directive="sys",
        transcript=transcript,
        prune=lambda messages, keep_recent: pruned.append((messages, keep_recent)),
    )

    assert result.completion is completion
    assert result.collapse_reset is True
    assert pruned == [(transcript, 4)]
    assert provider.calls[1]["messages"] == [
        {"role": "system", "content": "sys"},
        *transcript,
    ]


def test_generate_with_context_recovery_propagates_second_context_error():
    provider = Provider(side_effect=[
        ContextWindowError("too large"),
        ContextWindowError("still too large"),
    ])

    with pytest.raises(ContextWindowError, match="still too large"):
        generate_with_context_recovery(
            provider=provider,
            wire_messages=[],
            tool_schemas=[],
            on_token=None,
            directive="sys",
            transcript=[],
        )

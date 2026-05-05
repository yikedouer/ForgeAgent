"""Autocompact tier tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from forgecc.context.compaction_autocompact import (
    MAX_CONSECUTIVE_FAILURES,
    _autocompact,
    _extract_recent_file_paths,
)


def _tool_call(call_id: str, name: str, arguments: str = "{}") -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _assistant_msg(text: str = "", tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def _system_msg(text: str = "You are a helpful assistant.") -> dict:
    return {"role": "system", "content": text}


def test_autocompact_inserts_summary() -> None:
    provider = MagicMock()
    completion = MagicMock()
    completion.text = "Summary of conversation"
    provider.generate.return_value = completion

    msgs = [_system_msg()] + [_user_msg(f"msg{i}") for i in range(12)]

    assert _autocompact(msgs, provider, keep_recent=4) is True
    assert any("AUTOCOMPACT SUMMARY" in m.get("content", "") for m in msgs)


def test_autocompact_llm_failure_increments_count() -> None:
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM error")
    msgs = [_system_msg()] + [_user_msg(f"msg{i}") for i in range(12)]
    failure_count = [0]

    assert _autocompact(
        msgs,
        provider,
        keep_recent=4,
        failure_count=failure_count,
    ) is False
    assert failure_count[0] == 1


def test_autocompact_circuit_breaker_skips_provider() -> None:
    provider = MagicMock()
    msgs = [_system_msg()] + [_user_msg(f"msg{i}") for i in range(12)]
    failure_count = [MAX_CONSECUTIVE_FAILURES]

    assert _autocompact(
        msgs,
        provider,
        keep_recent=4,
        failure_count=failure_count,
    ) is False
    provider.generate.assert_not_called()


def test_autocompact_too_few_messages_noops() -> None:
    provider = MagicMock()
    msgs = [_system_msg(), _user_msg("hi")]

    assert _autocompact(msgs, provider, keep_recent=4) is False


def test_autocompact_success_resets_failure_count() -> None:
    provider = MagicMock()
    completion = MagicMock()
    completion.text = "Summary"
    provider.generate.return_value = completion
    msgs = [_system_msg()] + [_user_msg(f"msg{i}") for i in range(12)]
    failure_count = [2]

    _autocompact(msgs, provider, keep_recent=4, failure_count=failure_count)

    assert failure_count[0] == 0


def test_autocompact_skips_non_object_messages() -> None:
    provider = MagicMock()
    completion = MagicMock()
    completion.text = "Summary"
    provider.generate.return_value = completion
    msgs = [_system_msg(), "not-a-message"] + [
        _user_msg(f"msg{i}") for i in range(12)
    ]

    assert _autocompact(msgs, provider, keep_recent=4) is True
    segment_text = provider.generate.call_args.args[0][1]["content"]
    assert "not-a-message" not in segment_text


def test_extract_recent_file_paths_skips_non_object_messages() -> None:
    msgs = [
        "not-a-message",
        _assistant_msg("", [_tool_call("c1", "edit_file", '{"path": "/tmp/a.py"}')]),
    ]

    assert _extract_recent_file_paths(msgs) == ["/tmp/a.py"]


def test_extract_recent_file_paths_ignores_malformed_function_payloads() -> None:
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "bad", "function": "bad"}]},
        _assistant_msg("", [_tool_call("c1", "edit_file", '{"path": "/tmp/a.py"}')]),
    ]

    assert _extract_recent_file_paths(msgs) == ["/tmp/a.py"]

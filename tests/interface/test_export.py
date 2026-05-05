"""Conversation export rendering tests."""

import json


def test_render_transcript_markdown_includes_session_count_and_messages():
    from forgeagent.interface.export import render_transcript_markdown

    markdown = render_transcript_markdown(
        "s1",
        [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ],
    )

    assert "- **Session**: `s1`" in markdown
    assert "- **Messages**: 2" in markdown
    assert "## 1. User" in markdown
    assert "Hello" in markdown
    assert markdown.endswith("\n")


def test_render_events_jsonl_outputs_one_json_object_per_line():
    from forgeagent.interface.export import render_events_jsonl

    events = [
        {"type": "checkpoint", "session_id": "s1"},
        {"type": "message", "message": {"role": "user", "content": "你好"}},
    ]

    output = render_events_jsonl(events)

    assert [json.loads(line) for line in output.splitlines()] == events
    assert output.endswith("\n")


def test_render_events_jsonl_returns_empty_string_for_no_events():
    from forgeagent.interface.export import render_events_jsonl

    assert render_events_jsonl([]) == ""

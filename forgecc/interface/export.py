"""Conversation export renderers."""

from __future__ import annotations

import json


def render_transcript_markdown(session_id: str, messages: list[dict]) -> str:
    """Render a conversation transcript as Markdown."""
    lines = [
        "# Conversation Export",
        "",
        f"- **Session**: `{session_id}`",
        f"- **Messages**: {len(messages)}",
        "",
    ]
    for idx, message in enumerate(messages, start=1):
        role = str(message.get("role", "unknown")).title()
        content = str(message.get("content", ""))
        lines.extend([f"## {idx}. {role}", "", content, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_events_jsonl(events: list[dict]) -> str:
    """Render checkpoint events as newline-delimited JSON."""
    lines = [
        json.dumps(event, ensure_ascii=False)
        for event in events
    ]
    return "\n".join(lines) + ("\n" if lines else "")

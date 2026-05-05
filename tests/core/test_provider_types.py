"""Provider response type tests."""

from __future__ import annotations

import json

from forgeagent.core.providers import Completion, Invocation


def test_completion_raw_assistant_msg_with_text_only() -> None:
    msg = Completion(text="hello").raw_assistant_msg

    assert msg == {"role": "assistant", "content": "hello"}


def test_completion_raw_assistant_msg_sanitizes_tool_call_payload() -> None:
    args = {}
    args["self"] = args
    msg = Completion(
        invocations=[
            Invocation(call_id=["bad"], fn_name=["bad"], fn_args=args),
        ],
    ).raw_assistant_msg

    assert msg["tool_calls"][0]["id"] == "call_0"
    assert msg["tool_calls"][0]["function"]["name"] == "unknown_tool"
    arguments = json.loads(msg["tool_calls"][0]["function"]["arguments"])
    assert arguments == {"_raw": "{'self': {...}}"}

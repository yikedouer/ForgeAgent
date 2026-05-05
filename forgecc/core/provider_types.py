"""Structured provider response types."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


def _json_argument_string(value) -> str:
    if not isinstance(value, dict):
        return json.dumps({"_raw": str(value)})
    try:
        return json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps({"_raw": str(value)})


@dataclass
class Invocation:
    """A single tool invocation requested by the model."""
    call_id: str
    fn_name: str
    fn_args: dict


@dataclass
class Completion:
    """Parsed model response: text, tool calls, or both."""
    text: str = ""
    invocations: list[Invocation] = field(default_factory=list)
    usage_in: int = 0
    usage_out: int = 0

    @property
    def raw_assistant_msg(self) -> dict:
        """Rebuild an OpenAI-format assistant message."""
        msg: dict = {"role": "assistant", "content": self.text or None}
        if self.invocations:
            msg["tool_calls"] = [
                {
                    "id": inv.call_id if isinstance(inv.call_id, str) and inv.call_id else f"call_{idx}",
                    "type": "function",
                    "function": {
                        "name": inv.fn_name if isinstance(inv.fn_name, str) and inv.fn_name else "unknown_tool",
                        "arguments": _json_argument_string(inv.fn_args),
                    },
                }
                for idx, inv in enumerate(self.invocations)
            ]
        return msg

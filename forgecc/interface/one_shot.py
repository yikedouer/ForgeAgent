"""One-shot prompt execution for the CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def close_engine(engine: object) -> None:
    close = getattr(engine, "close", None)
    if callable(close):
        close()


def run_prompt_once(
    engine: Any,
    prompt: str,
    *,
    output_format: str,
    output_console: Any,
    on_token: Callable[[str], None] | None = None,
    on_tool: Callable[[str, object], None] | None = None,
) -> None:
    """Run a single prompt and emit the requested CLI output format."""
    try:
        if output_format == "json":
            answer = engine.run(prompt)
            t_in = getattr(engine, "_total_input_tokens", engine.provider.tokens_used[0])
            t_out = getattr(engine, "_total_output_tokens", engine.provider.tokens_used[1])
            output_console.print(json.dumps(
                {
                    "kind": "response",
                    "message": answer,
                    "model": engine.settings.model,
                    "session_id": engine.session_id,
                    "usage": {
                        "input_tokens": t_in,
                        "output_tokens": t_out,
                    },
                },
                ensure_ascii=False,
            ))
            return

        answer = engine.run(
            prompt,
            on_token=on_token,
            on_tool=on_tool,
        )
        if answer:
            output_console.print()
    finally:
        close_engine(engine)

"""One-shot CLI prompt execution tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from forgecc.interface.one_shot import run_prompt_once


def test_run_prompt_once_emits_json_response_and_closes_engine() -> None:
    engine = MagicMock()
    engine.run.return_value = "done"
    engine.settings.model = "qwen3.6-plus"
    engine.session_id = "s-json"
    engine.provider.tokens_used = (0, 0)
    engine._total_input_tokens = 12
    engine._total_output_tokens = 34
    output_console = MagicMock()

    run_prompt_once(
        engine,
        "hello",
        output_format="json",
        output_console=output_console,
    )

    engine.run.assert_called_once_with("hello")
    parsed = json.loads(output_console.print.call_args.args[0])
    assert parsed == {
        "kind": "response",
        "message": "done",
        "model": "qwen3.6-plus",
        "session_id": "s-json",
        "usage": {"input_tokens": 12, "output_tokens": 34},
    }
    engine.close.assert_called_once_with()


def test_run_prompt_once_streams_text_response_and_closes_engine() -> None:
    engine = MagicMock()
    engine.run.return_value = "done"
    output_console = MagicMock()
    on_token = MagicMock()
    on_tool = MagicMock()

    run_prompt_once(
        engine,
        "hello",
        output_format="text",
        output_console=output_console,
        on_token=on_token,
        on_tool=on_tool,
    )

    engine.run.assert_called_once_with(
        "hello",
        on_token=on_token,
        on_tool=on_tool,
    )
    output_console.print.assert_called_once_with()
    engine.close.assert_called_once_with()


def test_run_prompt_once_closes_engine_after_failure() -> None:
    engine = MagicMock()
    engine.run.side_effect = RuntimeError("boom")
    output_console = MagicMock()

    try:
        run_prompt_once(
            engine,
            "hello",
            output_format="text",
            output_console=output_console,
        )
    except RuntimeError:
        pass

    engine.close.assert_called_once_with()

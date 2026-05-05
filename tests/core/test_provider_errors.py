"""Provider error classification tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from openai import APIConnectionError, RateLimitError

from forgecc.core.provider_errors import _is_context_window_error, _should_retry


def test_context_window_error_detected_from_message() -> None:
    assert _is_context_window_error(Exception("token limit reached")) is True


def test_should_retry_connection_and_rate_limit_errors() -> None:
    rate_limited = RateLimitError.__new__(RateLimitError)
    connection = APIConnectionError.__new__(APIConnectionError)
    connection.__init__(request=MagicMock())

    assert _should_retry(rate_limited) is True
    assert _should_retry(connection) is True

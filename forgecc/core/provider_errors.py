"""Provider error classification helpers."""

from __future__ import annotations

from openai import APIConnectionError, APIError, RateLimitError


_RETRYABLE_CODES = {429, 502, 503}
_CONTEXT_WINDOW_CODES = {400, 413}


def _is_context_window_error(exc: Exception) -> bool:
    """Detect provider context-window failures across compatible APIs."""
    msg = str(exc).lower()
    indicators = (
        "context length",
        "context window",
        "maximum context",
        "token limit",
        "too many tokens",
        "reduce your prompt",
        "max_tokens",
        "input too long",
    )
    if any(ind in msg for ind in indicators):
        return True
    if isinstance(exc, APIError) and getattr(exc, "status_code", 0) in _CONTEXT_WINDOW_CODES:
        if any(ind in msg for ind in indicators):
            return True
    return False


def _should_retry(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIError) and getattr(exc, "status_code", 0) in _RETRYABLE_CODES:
        return True
    if isinstance(exc, APIConnectionError):
        return True
    return False

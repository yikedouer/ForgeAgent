"""LLM provider — thin adapter over any OpenAI-compatible endpoint.

Responsibilities:
  * Streaming chat completion with tool declarations
  * Exponential back-off for transient failures (429 / 502 / 503)
  * Token accounting for cost awareness
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from openai import OpenAI, APIError, APIConnectionError, RateLimitError, AuthenticationError

from .settings import Settings
from .errors import (
    ProviderError, ContextWindowError,
    AuthenticationError as ForgeAuthError,
    RateLimitedError,
)


# ── Structured response ─────────────────────────────────────

@dataclass
class Invocation:
    """A single tool-call request returned by the model."""
    call_id: str
    fn_name: str
    fn_args: dict


@dataclass
class Completion:
    """Parsed model response — either text, tool invocations, or both."""
    text: str = ""
    invocations: list[Invocation] = field(default_factory=list)
    usage_in: int = 0
    usage_out: int = 0

    @property
    def raw_assistant_msg(self) -> dict:
        """Reconstruct the OpenAI-format assistant message."""
        msg: dict = {"role": "assistant", "content": self.text or None}
        if self.invocations:
            msg["tool_calls"] = [
                {
                    "id": inv.call_id,
                    "type": "function",
                    "function": {
                        "name": inv.fn_name,
                        "arguments": json.dumps(inv.fn_args),
                    },
                }
                for inv in self.invocations
            ]
        return msg


# ── Retry policy ────────────────────────────────────────────

_RETRYABLE_CODES = {429, 502, 503}
_CONTEXT_WINDOW_CODES = {400, 413}
_MAX_ATTEMPTS = 4
_BASE_DELAY = 1.5


def _is_context_window_error(exc: Exception) -> bool:
    """Detect context-window-exceeded errors from various providers."""
    msg = str(exc).lower()
    indicators = ("context length", "context window", "maximum context",
                  "token limit", "too many tokens", "reduce your prompt",
                  "max_tokens", "input too long")
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


# ── Provider ────────────────────────────────────────────────

class Provider:
    """Stateful wrapper around a single OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings):
        self._client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
        self._model = settings.model
        self._total_in = 0
        self._total_out = 0

    # ── public ──

    def generate(
        self,
        messages: list[dict],
        tool_schemas: list[dict] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> Completion:
        """Send a chat-completion request with optional streaming.

        Raises:
            ContextWindowError: when context is too large (engine should compact)
            ForgeAuthError: when API key is invalid
            RateLimitedError: when rate limited (after exhausting retries)
            ProviderError: for other API failures
        """
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._call(messages, tool_schemas, on_token)
            except Exception as exc:
                # classify the error
                if _is_context_window_error(exc):
                    raise ContextWindowError(str(exc)) from exc
                if isinstance(exc, AuthenticationError):
                    raise ForgeAuthError(str(exc)) from exc
                if attempt == _MAX_ATTEMPTS - 1 or not _should_retry(exc):
                    # wrap unclassified errors
                    if isinstance(exc, (ProviderError,)):
                        raise
                    status = getattr(exc, "status_code", 0)
                    raise ProviderError(
                        str(exc), retryable=False, status_code=status
                    ) from exc
                wait = _BASE_DELAY * (2 ** attempt)
                time.sleep(wait)
        raise ProviderError("exhausted retries")

    @property
    def tokens_used(self) -> tuple[int, int]:
        return self._total_in, self._total_out

    # ── private ──

    def _call(
        self,
        messages: list[dict],
        tool_schemas: list[dict] | None,
        on_token: Callable[[str], None] | None,
    ) -> Completion:
        kwargs: dict = dict(model=self._model, messages=messages, stream=True)
        if tool_schemas:
            kwargs["tools"] = [
                {"type": "function", "function": s} for s in tool_schemas
            ]

        stream = self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        call_map: dict[int, dict] = {}  # index -> {id, name, args_buf}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # accumulate text
            if delta.content:
                text_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)

            # accumulate tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in call_map:
                        call_map[idx] = {"id": "", "name": "", "args_buf": ""}
                    if tc_delta.id:
                        call_map[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            call_map[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            call_map[idx]["args_buf"] += tc_delta.function.arguments

            # grab usage from the final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                u_in = chunk.usage.prompt_tokens or 0
                u_out = chunk.usage.completion_tokens or 0
            else:
                u_in = u_out = 0

        # parse accumulated tool calls
        invocations = []
        for idx in sorted(call_map):
            entry = call_map[idx]
            try:
                args = json.loads(entry["args_buf"]) if entry["args_buf"] else {}
            except json.JSONDecodeError:
                args = {"_raw": entry["args_buf"]}
            invocations.append(Invocation(
                call_id=entry["id"],
                fn_name=entry["name"],
                fn_args=args,
            ))

        self._total_in += u_in
        self._total_out += u_out

        return Completion(
            text="".join(text_parts),
            invocations=invocations,
            usage_in=u_in,
            usage_out=u_out,
        )

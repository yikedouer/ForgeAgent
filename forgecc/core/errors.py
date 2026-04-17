"""Structured error hierarchy for ForgeCC.

All ForgeCC-specific exceptions inherit from ForgeError so callers can
catch the entire family with a single except clause when desired.

Key error types:
  ProviderError    — LLM API failures, subdivided by retryability
  ContextWindowError — special case: context too large, auto-compact can help
  ToolError        — instrument execution failures
  PermissionDenied — permission enforcer blocked the operation
"""

from __future__ import annotations


class ForgeError(Exception):
    """Base class for all ForgeCC errors."""
    pass


# ── Provider errors ────────────────────────────────────────

class ProviderError(ForgeError):
    """LLM API call failed."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ContextWindowError(ProviderError):
    """Context window exceeded — the conversation is too large.

    The engine should catch this, trigger compaction, and retry.
    """

    def __init__(self, message: str = "Context window exceeded"):
        super().__init__(message, retryable=False, status_code=400)


class AuthenticationError(ProviderError):
    """Invalid or missing API credentials."""

    def __init__(self, message: str = "Authentication failed — check your API key"):
        super().__init__(message, retryable=False, status_code=401)


class RateLimitedError(ProviderError):
    """Rate limited by the provider — retryable with backoff."""

    def __init__(self, message: str = "Rate limited — retrying"):
        super().__init__(message, retryable=True, status_code=429)


# ── Tool errors ────────────────────────────────────────────

class ToolError(ForgeError):
    """An instrument execution failed."""

    def __init__(self, tool_name: str, message: str):
        super().__init__(f"[{tool_name}] {message}")
        self.tool_name = tool_name


# ── Permission errors ──────────────────────────────────────

class PermissionDenied(ForgeError):
    """The permission enforcer blocked the operation."""

    def __init__(self, tool_name: str, reason: str):
        super().__init__(f"Permission denied for '{tool_name}': {reason}")
        self.tool_name = tool_name
        self.reason = reason

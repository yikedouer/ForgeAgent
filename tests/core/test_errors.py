"""test_errors.py — 异常层级测试。"""

from __future__ import annotations

import pytest

from forgeagent.core.errors import (
    ForgeError,
    ProviderError,
    ContextWindowError,
    AuthenticationError,
    RateLimitedError,
    ToolError,
    PermissionDenied,
)


class TestInheritanceChain:
    def test_context_window_is_provider_error(self):
        assert isinstance(ContextWindowError(), ProviderError)

    def test_context_window_is_forge_error(self):
        assert isinstance(ContextWindowError(), ForgeError)

    def test_auth_is_provider_error(self):
        assert isinstance(AuthenticationError(), ProviderError)

    def test_rate_limited_is_provider_error(self):
        assert isinstance(RateLimitedError(), ProviderError)

    def test_tool_error_is_forge_error(self):
        assert isinstance(ToolError("t", "msg"), ForgeError)

    def test_permission_denied_is_forge_error(self):
        assert isinstance(PermissionDenied("t", "r"), ForgeError)


class TestProviderErrorAttributes:
    def test_retryable_default(self):
        e = ProviderError("fail")
        assert e.retryable is False
        assert e.status_code == 0

    def test_context_window_not_retryable(self):
        e = ContextWindowError()
        assert e.retryable is False
        assert e.status_code == 400

    def test_auth_not_retryable(self):
        e = AuthenticationError()
        assert e.retryable is False
        assert e.status_code == 401

    def test_rate_limited_retryable(self):
        e = RateLimitedError()
        assert e.retryable is True
        assert e.status_code == 429


class TestToolAndPermissionErrors:
    def test_tool_error_carries_name(self):
        e = ToolError("shell", "timeout")
        assert e.tool_name == "shell"
        assert "shell" in str(e)
        assert "timeout" in str(e)

    def test_permission_denied_carries_fields(self):
        e = PermissionDenied("write_file", "readonly mode")
        assert e.tool_name == "write_file"
        assert e.reason == "readonly mode"
        assert "write_file" in str(e)

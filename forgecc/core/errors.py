"""结构化错误层级。

所有 ForgeCC 异常均继承自 ForgeError，调用方可用单个 except 子句
捕获整个异常族。

主要错误类型：
  ProviderError     — LLM API 失败，按可重试性细分
  ContextWindowError — 上下文过大，可触发自动压缩
  ToolError         — 工具执行失败
  PermissionDenied  — 权限执行器拦截了操作
"""

from __future__ import annotations


class ForgeError(Exception):
    """所有 ForgeCC 错误的基类。"""
    pass


# ── Provider 错误 ──────────────────────────────────────────

class ProviderError(ForgeError):
    """LLM API 调用失败。"""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ContextWindowError(ProviderError):
    """上下文窗口超出 — 对话太大。

    Engine 应捕获此异常，触发压缩后重试。
    """

    def __init__(self, message: str = "Context window exceeded"):
        super().__init__(message, retryable=False, status_code=400)


class AuthenticationError(ProviderError):
    """无效或缺失的 API 凭证。"""

    def __init__(self, message: str = "Authentication failed — check your API key"):
        super().__init__(message, retryable=False, status_code=401)


class RateLimitedError(ProviderError):
    """被 Provider 限流 — 可退避重试。"""

    def __init__(self, message: str = "Rate limited — retrying"):
        super().__init__(message, retryable=True, status_code=429)


# ── 工具错误 ────────────────────────────────────────────

class ToolError(ForgeError):
    """工具执行失败。"""

    def __init__(self, tool_name: str, message: str):
        super().__init__(f"[{tool_name}] {message}")
        self.tool_name = tool_name


# ── 权限错误 ────────────────────────────────────────────

class PermissionDenied(ForgeError):
    """权限执行器拦截了操作。"""

    def __init__(self, tool_name: str, reason: str):
        super().__init__(f"Permission denied for '{tool_name}': {reason}")
        self.tool_name = tool_name
        self.reason = reason

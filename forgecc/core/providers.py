"""LLM Provider — 对 OpenAI 兼容端点和 Azure OpenAI 的薄封装。

职责：
  * 根据 ``Settings.client_type`` 自动选择 ``OpenAI`` 或 ``AzureOpenAI`` 客户端
  * 流式 chat completion + 工具声明
  * 暂态失败的指数退避重试（429 / 502 / 503）
  * Token 计数用于成本感知
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from openai import (
    APIConnectionError, APIError,
    OpenAI, AzureOpenAI,
    RateLimitError, AuthenticationError,
)

from .settings import Settings
from .errors import (
    ProviderError, ContextWindowError,
    AuthenticationError as ForgeAuthError,
    RateLimitedError,
)
from .log import get_logger

log = get_logger(__name__)


_RETRYABLE_CODES = {429, 502, 503}
_CONTEXT_WINDOW_CODES = {400, 413}


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


def _field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _tool_call_index(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _usage_token_count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _string_delta(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _with_prompt_cache(messages: list[dict]) -> list[dict]:
    """Return a copy with the first string system message marked cacheable."""
    prepared = [dict(message) for message in messages]
    if not prepared:
        return prepared
    first = prepared[0]
    if first.get("role") != "system" or not isinstance(first.get("content"), str):
        return prepared
    first["content"] = [
        {
            "type": "text",
            "text": first["content"],
            "cache_control": {"type": "ephemeral"},
        }
    ]
    return prepared


_MAX_ATTEMPTS = 4
_BASE_DELAY = 1.5


# ── Provider ────────────────────────────────────────────────

class Provider:
    """单个 LLM 端点的有状态封装。支持标准 OpenAI、Azure OpenAI 和公司内部代理。"""

    def __init__(self, settings: Settings):
        # 公司内部代理（iai.alibaba-inc.com）需要 empId 请求头
        headers = None
        if "iai.alibaba-inc.com" in settings.base_url:
            emp_id = (
                os.environ.get("FORGECC_EMP_ID")
                or os.environ.get("AZURE_EMP_ID", "")  # 向后兼容
            )
            if emp_id:
                headers = {"empId": emp_id}

        if settings.client_type == "azure":
            # Azure OpenAI 客户端（公司内部代理访问 GPT）
            self._client = AzureOpenAI(
                api_key=settings.api_key,
                api_version=settings.api_version or "2024-12-01-preview",
                azure_endpoint=settings.base_url,
                default_headers=headers,
            )
            log.info("Provider 初始化 [Azure]  model=%s  endpoint=%s",
                     settings.model, settings.base_url)
        else:
            # 标准 OpenAI 兼容模式（Qwen / DeepSeek / Gemini 等）
            client_kwargs: dict = dict(
                api_key=settings.api_key, base_url=settings.base_url
            )
            if headers:
                client_kwargs["default_headers"] = headers
            self._client = OpenAI(**client_kwargs)
            log.info("Provider 初始化  model=%s  base_url=%s",
                     settings.model, settings.base_url)
        self._model = settings.model
        self._prompt_cache = settings.prompt_cache
        self._total_in = 0
        self._total_out = 0

    # ── 公开接口 ──

    def generate(
        self,
        messages: list[dict],
        tool_schemas: list[dict] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> Completion:
        """发送 chat-completion 请求，支持可选流式输出。

        异常：
            ContextWindowError: 上下文过大（Engine 应压缩）
            ForgeAuthError: API key 无效
            RateLimitedError: 被限流（重试耗尽后）
            ProviderError: 其他 API 失败
        """
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._call(messages, tool_schemas, on_token)
            except Exception as exc:
                log.debug("LLM 调用异常 (attempt %d/%d): %s",
                          attempt + 1, _MAX_ATTEMPTS, exc)
                # 分类错误
                if _is_context_window_error(exc):
                    raise ContextWindowError(str(exc)) from exc
                if isinstance(exc, AuthenticationError):
                    raise ForgeAuthError(str(exc)) from exc
                if attempt == _MAX_ATTEMPTS - 1 or not _should_retry(exc):
                    # 包装未分类的错误
                    log.error("LLM 调用最终失败: %s", exc)
                    if isinstance(exc, (ProviderError,)):
                        raise
                    status = getattr(exc, "status_code", 0)
                    if isinstance(exc, RateLimitError) or status == 429:
                        raise RateLimitedError(str(exc)) from exc
                    raise ProviderError(
                        str(exc), retryable=False, status_code=status
                    ) from exc
                wait = _BASE_DELAY * (2 ** attempt)
                log.info("重试等待 %.1f秒...", wait)
                time.sleep(wait)
        raise ProviderError("exhausted retries")

    @property
    def tokens_used(self) -> tuple[int, int]:
        return self._total_in, self._total_out

    def side_query(self, system: str, user_message: str, max_tokens: int = 256) -> str:
        """轻量级非流式调用，用于辅助查询（记忆召回等）。"""
        log.debug("side_query: system=%d字  user=%d字  max_tokens=%d",
                  len(system), len(user_message), max_tokens)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            stream=False,
        )
        choices = _field(response, "choices", None)
        if not choices:
            # 公司内部代理的错误格式：choices=None + message 字段包含错误信息
            error_message = _field(response, "message", "API returned no choices")
            raise ProviderError(str(error_message)[:500])
        message = _field(choices[0], "message", None)
        return _field(message, "content", "") or ""

    # ── 私有实现 ──

    def _call(
        self,
        messages: list[dict],
        tool_schemas: list[dict] | None,
        on_token: Callable[[str], None] | None,
    ) -> Completion:
        kwargs: dict = dict(
            model=self._model,
            messages=_with_prompt_cache(messages) if self._prompt_cache else messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tool_schemas:
            kwargs["tools"] = [
                {"type": "function", "function": s} for s in tool_schemas
            ]

        stream = self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tool_call_parts: dict[int, dict] = {}
        usage_in = usage_out = 0

        for chunk in stream:
            # 最后一个 chunk（choices 为空）仅携带 usage 统计
            usage = _field(chunk, "usage", None)
            if usage:
                usage_in = _usage_token_count(_field(usage, "prompt_tokens", 0))
                usage_out = _usage_token_count(_field(usage, "completion_tokens", 0))

            choices = _field(chunk, "choices", None)
            delta = _field(choices[0], "delta", None) if choices else None
            if delta is None:
                continue

            # 累积文本
            content = _field(delta, "content", None)
            if content:
                text_parts.append(content)
                if on_token:
                    try:
                        on_token(content)
                    except Exception as exc:
                        log.warning("token 回调异常: %s", exc)

            # 累积工具调用 delta
            tool_calls = _field(delta, "tool_calls", None)
            if isinstance(tool_calls, (list, tuple)):
                for tool_call_delta in tool_calls:
                    call_index = _tool_call_index(
                        _field(tool_call_delta, "index", 0)
                    )
                    call_id = _string_delta(_field(tool_call_delta, "id", None))
                    function = _field(tool_call_delta, "function", None)
                    name = None
                    arguments = None
                    if function:
                        name = _string_delta(_field(function, "name", None))
                        arguments = _field(function, "arguments", None)
                    has_arguments = arguments is not None and arguments != ""
                    if not (call_id or name or has_arguments):
                        continue
                    if call_index not in tool_call_parts:
                        tool_call_parts[call_index] = {"id": "", "name": "", "args_buf": ""}
                    if call_id:
                        tool_call_parts[call_index]["id"] = call_id
                    if name:
                        tool_call_parts[call_index]["name"] = name
                    if has_arguments:
                        if not isinstance(arguments, str):
                            try:
                                arguments = json.dumps(arguments)
                            except (TypeError, ValueError):
                                arguments = str(arguments)
                        tool_call_parts[call_index]["args_buf"] += arguments

        # 解析累积的工具调用
        invocations = []
        for call_index in sorted(tool_call_parts):
            entry = tool_call_parts[call_index]
            if not entry["name"]:
                continue
            try:
                args = json.loads(entry["args_buf"]) if entry["args_buf"] else {}
                if not isinstance(args, dict):
                    args = {"_raw": entry["args_buf"]}
            except json.JSONDecodeError:
                args = {"_raw": entry["args_buf"]}
            invocations.append(Invocation(
                call_id=entry["id"] or f"call_{call_index}",
                fn_name=entry["name"],
                fn_args=args,
            ))

        self._total_in += usage_in
        self._total_out += usage_out
        log.debug("流式响应完成: in=%d out=%d  文本=%d字  工具=%d个",
                  usage_in, usage_out, len("".join(text_parts)), len(tool_call_parts))

        return Completion(
            text="".join(text_parts),
            invocations=invocations,
            usage_in=usage_in,
            usage_out=usage_out,
        )

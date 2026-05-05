"""test_providers.py — LLM Provider 测试（Mock OpenAI 客户端）。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

from forgeagent.core.providers import (
    Invocation,
    Completion,
    Provider,
    _is_context_window_error,
    _should_retry,
)
from forgeagent.core.errors import ContextWindowError, RateLimitedError
from forgeagent.core.settings import Settings
from openai import APIError, APIConnectionError, RateLimitError, AuthenticationError


# ═══════════════════════════════════════════════════════════
# 7.3 异常分类辅助函数
# ═══════════════════════════════════════════════════════════

class TestErrorClassification:
    def test_context_window_by_message(self):
        exc = Exception("context length exceeded")
        assert _is_context_window_error(exc) is True

    def test_context_window_token_limit(self):
        exc = Exception("token limit reached")
        assert _is_context_window_error(exc) is True

    def test_not_context_window(self):
        exc = Exception("some random error")
        assert _is_context_window_error(exc) is False

    def test_should_retry_rate_limit(self):
        exc = RateLimitError.__new__(RateLimitError)
        assert _should_retry(exc) is True

    def test_should_retry_connection(self):
        exc = APIConnectionError.__new__(APIConnectionError)
        exc.__init__(request=MagicMock())
        assert _should_retry(exc) is True

    def test_should_not_retry_auth(self):
        exc = Exception("auth failed")
        assert _should_retry(exc) is False


# ═══════════════════════════════════════════════════════════
# 7.2/7.5/7.6 Provider（Mock 客户端）
# ═══════════════════════════════════════════════════════════

def _make_settings():
    return Settings(
        api_key="test", base_url="https://test/v1", model="m",
        context_budget=128000, max_rounds=60, workspace="/tmp",
        permission_mode="prompt",
    )


class TestProviderSideQuery:
    @patch("forgeagent.core.providers.OpenAI")
    def test_side_query_returns_text(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "answer"
        mock_client.chat.completions.create.return_value = mock_resp

        p = Provider(_make_settings())
        result = p.side_query("system", "user msg")
        assert result == "answer"

    @patch("forgeagent.core.providers.OpenAI")
    def test_side_query_accepts_dict_response(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "answer",
                    },
                },
            ],
        }

        p = Provider(_make_settings())
        result = p.side_query("system", "user msg")

        assert result == "answer"


class TestProviderTokens:
    @patch("forgeagent.core.providers.OpenAI")
    def test_initial_tokens_zero(self, MockOpenAI):
        p = Provider(_make_settings())
        assert p.tokens_used == (0, 0)


class TestProviderGenerate:
    @patch("forgeagent.core.providers.OpenAI")
    def test_prompt_cache_marks_system_message_when_enabled(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = []

        settings = _make_settings().replace(prompt_cache=True)
        p = Provider(settings)
        p.generate([
            {"role": "system", "content": "stable instructions"},
            {"role": "user", "content": "hi"},
        ])

        sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert sent_messages[0] == {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "stable instructions",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream(self, MockOpenAI):
        """模拟流式文本响应。"""
        mock_client = MockOpenAI.return_value

        # 构建 mock chunk
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello"
        chunk1.choices[0].delta.tool_calls = None
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " World"
        chunk2.choices[0].delta.tool_calls = None
        chunk2.usage = MagicMock()
        chunk2.usage.prompt_tokens = 10
        chunk2.usage.completion_tokens = 5

        mock_client.chat.completions.create.return_value = [chunk1, chunk2]

        p = Provider(_make_settings())
        tokens_collected = []
        result = p.generate(
            [{"role": "user", "content": "hi"}],
            on_token=lambda t: tokens_collected.append(t),
        )
        assert result.text == "Hello World"
        assert tokens_collected == ["Hello", " World"]
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_ignores_on_token_exception(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = [chunk]

        def broken_token_callback(_text):
            raise RuntimeError("ui down")

        p = Provider(_make_settings())
        result = p.generate(
            [{"role": "user", "content": "hi"}],
            on_token=broken_token_callback,
        )

        assert result.text == "Hello"
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_generate_raises_rate_limited_error_after_retries(self, MockOpenAI, monkeypatch):
        response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://test/v1/chat/completions"),
        )
        exc = RateLimitError("rate limited", response=response, body=None)
        monkeypatch.setattr("forgeagent.core.providers.time.sleep", lambda seconds: None)

        p = Provider(_make_settings())
        p._call = MagicMock(side_effect=exc)

        with pytest.raises(RateLimitedError):
            p.generate([{"role": "user", "content": "hi"}])

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_accepts_dict_chunks(self, MockOpenAI):
        """兼容 dict 形态的 chunk/choice/delta/usage。"""
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = [
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Hello",
                            "tool_calls": None,
                        }
                    }
                ],
                "usage": None,
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            },
        ]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_tolerates_partial_usage_fields(self, MockOpenAI):
        """兼容只返回部分 usage 字段的 OpenAI-like 端点。"""
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10),
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.usage_in == 10
        assert result.usage_out == 0

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_treats_bool_usage_tokens_as_zero(self, MockOpenAI):
        """bool 是 int 的子类，但 token 统计字段不应接受布尔值。"""
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=True, completion_tokens=False),
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.usage_in == 0
        assert result.usage_out == 0
        assert p.tokens_used == (0, 0)

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_tolerates_usage_chunk_without_choices(self, MockOpenAI):
        """兼容 usage-only chunk 缺少 choices 字段的 OpenAI-like 端点。"""
        mock_client = MockOpenAI.return_value
        text_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None)
                )
            ],
            usage=None,
        )
        usage_chunk = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = [text_chunk, usage_chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_tolerates_choice_without_delta(self, MockOpenAI):
        """兼容 choice 缺少 delta 字段的空分片。"""
        mock_client = MockOpenAI.return_value
        text_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hello", tool_calls=None)
                )
            ],
            usage=None,
        )
        empty_choice_chunk = SimpleNamespace(
            choices=[SimpleNamespace()],
            usage=None,
        )
        usage_chunk = SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = [
            text_chunk,
            empty_choice_chunk,
            usage_chunk,
        ]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_tolerates_non_iterable_tool_calls(self, MockOpenAI):
        """兼容 delta.tool_calls 不是可迭代列表的异常分片。"""
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="Hello",
                        tool_calls=SimpleNamespace(bad="shape"),
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "Hello"
        assert result.invocations == []
        assert result.usage_in == 10
        assert result.usage_out == 5

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream(self, MockOpenAI):
        """模拟流式工具调用响应。"""
        mock_client = MockOpenAI.return_value

        tc_delta = MagicMock()
        tc_delta.index = 0
        tc_delta.id = "call_1"
        tc_delta.function = MagicMock()
        tc_delta.function.name = "read_file"
        tc_delta.function.arguments = '{"path": "/a.py"}'

        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        chunk.choices[0].delta.tool_calls = [tc_delta]
        chunk.usage = MagicMock()
        chunk.usage.prompt_tokens = 5
        chunk.usage.completion_tokens = 3

        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])
        assert len(result.invocations) == 1
        assert result.invocations[0].fn_name == "read_file"
        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_accepts_dict_tool_call_delta(self, MockOpenAI):
        """兼容 dict 形态的 tool call delta。"""
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "/a.py"},
                                },
                            }
                        ],
                    )
                )
            ],
            usage=None,
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert len(result.invocations) == 1
        assert result.invocations[0].call_id == "call_1"
        assert result.invocations[0].fn_name == "read_file"
        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_tolerates_malformed_index(self, MockOpenAI):
        """兼容 index 不是整数的异常工具调用分片。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=["bad"],
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == [
            Invocation(call_id="call_1", fn_name="read_file", fn_args={"path": "/a.py"})
        ]

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_treats_bool_index_as_malformed(self, MockOpenAI):
        """bool 是 int 的子类，但工具调用 index 不应接受布尔值。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=True,
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == [
            Invocation(call_id="call_0", fn_name="read_file", fn_args={"path": "/a.py"})
        ]

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_uses_fallback_for_malformed_call_id(self, MockOpenAI):
        """兼容 id 不是字符串的异常工具调用分片。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id=["bad"],
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == [
            Invocation(call_id="call_0", fn_name="read_file", fn_args={"path": "/a.py"})
        ]

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_skips_malformed_function_name(self, MockOpenAI):
        """函数名不是字符串时不生成异常 invocation。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(
                name=["bad"],
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == []

    @patch("forgeagent.core.providers.OpenAI")
    def test_text_stream_without_tool_calls_attribute(self, MockOpenAI):
        """兼容不在文本 delta 上发送 tool_calls 字段的端点。"""
        mock_client = MockOpenAI.return_value
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="hello")
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "hi"}])

        assert result.text == "hello"
        assert result.invocations == []

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_handles_missing_optional_delta_fields(self, MockOpenAI):
        """兼容工具调用分片里缺失 id/name 等可选字段。"""
        mock_client = MockOpenAI.return_value

        first = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(name="read_file", arguments='{"path"'),
        )
        second = SimpleNamespace(
            index=0,
            function=SimpleNamespace(arguments=': "/a.py"}'),
        )
        chunk1 = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[first])
                )
            ],
        )
        chunk2 = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[second])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk1, chunk2]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert len(result.invocations) == 1
        assert result.invocations[0].call_id == "call_1"
        assert result.invocations[0].fn_name == "read_file"
        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_synthesizes_missing_call_id(self, MockOpenAI):
        """兼容不返回工具调用 id 的端点，避免后续 tool 消息空 id。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].call_id == "call_0"

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_defaults_missing_index_for_single_call(self, MockOpenAI):
        """兼容单工具调用 delta 缺失 index 的端点。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].call_id == "call_1"
        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_defaults_none_index_for_single_call(self, MockOpenAI):
        """兼容 index=None 的单工具调用 delta。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=None,
            function=SimpleNamespace(
                name="read_file",
                arguments='{"path": "/a.py"}',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].call_id == "call_0"
        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_wraps_non_object_arguments(self, MockOpenAI):
        """工具参数 JSON 必须是 object；数组/字符串等合法 JSON 也要包装成 dict。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments='["not", "object"]',
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].fn_args == {"_raw": '["not", "object"]'}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_skips_empty_tool_call_delta(self, MockOpenAI):
        """空工具调用分片不应生成 fn_name 为空的假 invocation。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(index=0)
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == []

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_skips_call_without_function_name(self, MockOpenAI):
        """只有 arguments 但最终没有函数名的半成品调用应被忽略。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(arguments='{"path": "/a.py"}'),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations == []

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_accepts_object_arguments_delta(self, MockOpenAI):
        """兼容直接返回对象形式 function.arguments 的 OpenAI-like 端点。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments={"path": "/a.py"},
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].fn_args == {"path": "/a.py"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_wraps_unserializable_arguments_delta(self, MockOpenAI):
        """直接返回不可 JSON 序列化的 arguments 时不应让整次 Provider 调用失败。"""
        mock_client = MockOpenAI.return_value
        arguments = []
        arguments.append(arguments)
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments=arguments,
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].fn_args == {"_raw": "[[...]]"}

    @patch("forgeagent.core.providers.OpenAI")
    def test_tool_call_stream_wraps_empty_array_arguments_delta(self, MockOpenAI):
        """直接返回空数组 arguments 时仍按非 object 参数包装，不误判为空对象。"""
        mock_client = MockOpenAI.return_value
        tc_delta = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(
                name="read_file",
                arguments=[],
            ),
        )
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tc_delta])
                )
            ],
        )
        mock_client.chat.completions.create.return_value = [chunk]

        p = Provider(_make_settings())
        result = p.generate([{"role": "user", "content": "read"}])

        assert result.invocations[0].fn_args == {"_raw": "[]"}

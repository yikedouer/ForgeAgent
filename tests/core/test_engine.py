"""引擎集成测试 — forgecc.core.engine（重 Mock）"""

from __future__ import annotations

import os
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from forgecc.core.settings import Settings
from forgecc.core.permissions import PermissionMode
from forgecc.core.errors import ContextWindowError
from forgecc.core.mcp import MCPServerConfig


# ═══════════════════════════════════════════════════════════════
# Fixture: 构建 Engine 所需的 Mock 环境
# ═══════════════════════════════════════════════════════════════

def _make_settings(tmp_path) -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://test.example.com/v1",
        model="test-model",
        context_budget=128000,
        max_rounds=5,
        workspace=str(tmp_path),
        permission_mode="danger",  # 测试中跳过权限检查
    )


def _make_completion(text="Hello!", invocations=None, usage_in=10, usage_out=5):
    """创建一个 Mock Completion 对象。"""
    c = MagicMock()
    c.text = text
    c.invocations = invocations or []
    c.usage_in = usage_in
    c.usage_out = usage_out
    # raw_assistant_msg
    if invocations:
        c.raw_assistant_msg = {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {"id": inv.call_id, "function": {"name": inv.fn_name, "arguments": "{}"}}
                for inv in invocations
            ],
        }
    else:
        c.raw_assistant_msg = {"role": "assistant", "content": text}
    return c


def _make_invocation(call_id="c1", fn_name="read_file", fn_args=None):
    inv = MagicMock()
    inv.call_id = call_id
    inv.fn_name = fn_name
    inv.fn_args = fn_args or {}
    return inv


@pytest.fixture
def engine_env(tmp_path):
    """返回 (Engine, mock_provider)，已 patch 关键外部依赖。"""
    settings = _make_settings(tmp_path)
    provider = MagicMock()
    provider.tokens_used = (0, 0)
    provider._total_in = 0
    provider._total_out = 0

    # Patch maybe_start_memory_prefetch 避免真实线程池
    with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
         patch("forgecc.core.engine.persist_if_large", side_effect=lambda sid, name, out: out):
        from forgecc.core.engine import Engine
        eng = Engine(settings, provider)
        yield eng, provider


# ═══════════════════════════════════════════════════════════════
# 1. 初始化
# ═══════════════════════════════════════════════════════════════

class TestEngineInit:
    def test_session_id_length(self, engine_env):
        eng, _ = engine_env
        assert len(eng.session_id) == 12

    def test_transcript_empty(self, engine_env):
        eng, _ = engine_env
        assert eng.transcript == []

    def test_sub_agent_flag(self, tmp_path):
        settings = _make_settings(tmp_path)
        provider = MagicMock()
        provider.tokens_used = (0, 0)
        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None):
            from forgecc.core.engine import Engine
            eng = Engine(settings, provider, is_sub_agent=True)
            assert eng._is_sub_agent is True

    def test_main_engine_loads_configured_hook_files(self, tmp_path):
        settings = _make_settings(tmp_path).replace(
            hook_paths=("hooks/a.py", "hooks/b.py")
        )
        provider = MagicMock()
        provider.tokens_used = (0, 0)

        with patch("forgecc.core.engine.load_hook_file") as load_hook_file:
            from forgecc.core.engine import Engine

            Engine(settings, provider)

        assert [call.args[0] for call in load_hook_file.call_args_list] == [
            "hooks/a.py",
            "hooks/b.py",
        ]

    def test_main_engine_registers_configured_mcp_tools(self, tmp_path):
        settings = _make_settings(tmp_path).replace(
            mcp_servers=(MCPServerConfig(name="docs", command="uvx"),)
        )
        provider = MagicMock()
        provider.tokens_used = (0, 0)
        transport = MagicMock()
        client = MagicMock()

        with patch("forgecc.core.engine.StdioMCPTransport", return_value=transport) as transport_cls, \
             patch("forgecc.core.engine.MCPClient", return_value=client) as client_cls, \
             patch("forgecc.core.engine.toolkit.register_mcp_tools", return_value=("mcp__docs__search",)) as register:
            from forgecc.core.engine import Engine

            eng = Engine(settings, provider)

        transport_cls.assert_called_once_with(settings.mcp_servers[0])
        client_cls.assert_called_once_with(settings.mcp_servers[0], transport)
        client.initialize.assert_called_once_with()
        register.assert_called_once_with("docs", client)
        assert eng._mcp_transports == [transport]

    def test_sub_agent_skips_configured_mcp_servers(self, tmp_path):
        settings = _make_settings(tmp_path).replace(
            mcp_servers=(MCPServerConfig(name="docs", command="uvx"),)
        )
        provider = MagicMock()
        provider.tokens_used = (0, 0)

        with patch("forgecc.core.engine.StdioMCPTransport") as transport_cls:
            from forgecc.core.engine import Engine

            eng = Engine(settings, provider, is_sub_agent=True)

        transport_cls.assert_not_called()
        assert eng._mcp_transports == []

    def test_close_closes_mcp_transports(self, tmp_path):
        settings = _make_settings(tmp_path).replace(
            mcp_servers=(MCPServerConfig(name="docs", command="uvx"),)
        )
        provider = MagicMock()
        provider.tokens_used = (0, 0)
        transport = MagicMock()
        client = MagicMock()

        with patch("forgecc.core.engine.StdioMCPTransport", return_value=transport), \
             patch("forgecc.core.engine.MCPClient", return_value=client), \
             patch("forgecc.core.engine.toolkit.register_mcp_tools", return_value=("mcp__docs__search",)):
            from forgecc.core.engine import Engine

            eng = Engine(settings, provider)

        eng.close()

        transport.close.assert_called_once_with()

    def test_mcp_registration_failure_closes_started_transport(self, tmp_path):
        settings = _make_settings(tmp_path).replace(
            mcp_servers=(MCPServerConfig(name="docs", command="uvx"),)
        )
        provider = MagicMock()
        provider.tokens_used = (0, 0)
        transport = MagicMock()
        client = MagicMock()

        with patch("forgecc.core.engine.StdioMCPTransport", return_value=transport), \
             patch("forgecc.core.engine.MCPClient", return_value=client), \
             patch("forgecc.core.engine.toolkit.register_mcp_tools", side_effect=RuntimeError("boom")):
            from forgecc.core.engine import Engine

            eng = Engine(settings, provider)

        transport.close.assert_called_once_with()
        assert eng._mcp_transports == []


# ═══════════════════════════════════════════════════════════════
# 2. run() — 纯文本响应（无工具调用）
# ═══════════════════════════════════════════════════════════════

class TestRunBasic:
    def test_runtime_appends_message_events(self, engine_env):
        eng, provider = engine_env
        comp = _make_completion(text="Answer")
        provider.generate.return_value = comp

        with patch("forgecc.context.checkpoint.append_message_event") as append_event, \
             patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.core.engine.build_plan_mode_prompt", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="system prompt"):
            eng.run("Hello")

        assert [call.args for call in append_event.call_args_list] == [
            (eng.session_id, 0, {"role": "user", "content": "Hello"}),
            (eng.session_id, 1, {"role": "assistant", "content": "Answer"}),
        ]

    def test_pure_text(self, engine_env):
        eng, provider = engine_env
        comp = _make_completion(text="Answer")
        provider.generate.return_value = comp

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.core.engine.build_plan_mode_prompt", return_value=None):
            # Patch directive builder
            with patch("forgecc.interface.directive.build", return_value="system prompt"):
                result = eng.run("Hello")

        assert result == "Answer"
        assert len(eng.transcript) == 2  # user + assistant

    def test_successful_main_agent_turn_auto_saves_checkpoint(self, engine_env):
        from forgecc.context import checkpoint as ckpt

        eng, provider = engine_env
        provider.generate.return_value = _make_completion(text="Answer")

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.core.engine.build_plan_mode_prompt", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="system prompt"):
            eng.run("Hello")

        saved = ckpt.load(eng.session_id)
        assert saved.messages == eng.transcript
        assert saved.model == eng.settings.model

    def test_budget_exhausted(self, engine_env):
        eng, provider = engine_env
        eng.settings = eng.settings.replace(max_rounds=1)
        # 每次都返回带工具调用的响应 → 永远不结束
        inv = _make_invocation(call_id="c1", fn_name="read_file",
                                fn_args={"path": "/tmp/test"})
        comp = _make_completion(text="", invocations=[inv])
        provider.generate.return_value = comp

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"), \
             patch("forgecc.toolkit.run_batch") as mock_batch:
            mock_batch.return_value = [MagicMock(call_id="c1", name="read_file", output="ok")]
            result = eng.run("Do something")

        assert "budget exhausted" in result

    def test_non_object_tool_args_do_not_crash_logging(self, engine_env):
        from forgecc.toolkit import instrument

        @instrument("bad_args_tool", "test", {})
        def bad_args_tool() -> str:
            return "ok"

        eng, provider = engine_env
        inv = _make_invocation(call_id="c1", fn_name="bad_args_tool", fn_args=["bad"])
        comp_tools = _make_completion(text="", invocations=[inv])
        comp_done = _make_completion(text="done")
        provider.generate.side_effect = [comp_tools, comp_done]

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"):
            result = eng.run("Do something")

        assert result == "done"
        assert any(
            msg.get("role") == "tool" and "arguments must be an object" in msg.get("content", "")
            for msg in eng.transcript
        )

    def test_non_string_tool_name_does_not_crash_plan_split(self, engine_env):
        eng, provider = engine_env
        inv = _make_invocation(call_id="c1", fn_name=["bad"], fn_args={})
        comp_tools = _make_completion(text="", invocations=[inv])
        comp_done = _make_completion(text="done")
        provider.generate.side_effect = [comp_tools, comp_done]

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"):
            result = eng.run("Do something")

        assert result == "done"
        assert any(
            msg.get("role") == "tool" and "Invalid instrument name" in msg.get("content", "")
            for msg in eng.transcript
        )

    def test_on_instrument_exception_does_not_abort_tool_loop(self, engine_env):
        eng, provider = engine_env
        inv = _make_invocation(call_id="c1", fn_name="read_file", fn_args={"path": "/tmp/test"})
        comp_tools = _make_completion(text="", invocations=[inv])
        comp_done = _make_completion(text="done")
        provider.generate.side_effect = [comp_tools, comp_done]

        def broken_callback(_name, _args):
            raise RuntimeError("callback down")

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"), \
             patch("forgecc.toolkit.run_batch") as mock_batch:
            mock_batch.return_value = [MagicMock(call_id="c1", name="read_file", output="ok")]
            result = eng.run("Do something", on_instrument=broken_callback)

        assert result == "done"
        assert mock_batch.called

    def test_tool_result_persist_exception_keeps_original_output(self, engine_env):
        eng, provider = engine_env
        inv = _make_invocation(call_id="c1", fn_name="read_file", fn_args={"path": "/tmp/test"})
        comp_tools = _make_completion(text="", invocations=[inv])
        comp_done = _make_completion(text="done")
        provider.generate.side_effect = [comp_tools, comp_done]

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"), \
             patch("forgecc.toolkit.run_batch") as mock_batch, \
             patch("forgecc.core.engine.persist_if_large", side_effect=OSError("disk full")):
            mock_batch.return_value = [MagicMock(call_id="c1", name="read_file", output="raw output")]
            result = eng.run("Do something")

        assert result == "done"
        assert any(
            msg.get("role") == "tool" and msg.get("content") == "raw output"
            for msg in eng.transcript
        )


# ═══════════════════════════════════════════════════════════════
# 3. run() — ContextWindowError 恢复
# ═══════════════════════════════════════════════════════════════

class TestContextWindowRecovery:
    def test_prune_and_retry(self, engine_env):
        eng, provider = engine_env
        # 第一次调用抛 ContextWindowError，第二次正常返回
        comp_ok = _make_completion(text="Recovered")
        provider.generate.side_effect = [ContextWindowError("too big"), comp_ok]

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"):
            result = eng.run("Big prompt")

        assert result == "Recovered"


# ═══════════════════════════════════════════════════════════════
# 4. 计划模式
# ═══════════════════════════════════════════════════════════════

class TestPlanMode:
    def test_toggle_enter(self, engine_env):
        eng, _ = engine_env
        mode = eng.toggle_plan_mode()
        assert mode == "plan"
        assert eng.enforcer.mode == PermissionMode.PLAN
        assert eng._plan_file_path is not None

    def test_toggle_exit(self, engine_env):
        eng, _ = engine_env
        eng.toggle_plan_mode()  # enter
        mode = eng.toggle_plan_mode()  # exit
        assert mode != "plan"
        assert eng._plan_file_path is None

    def test_execute_enter_plan_mode(self, engine_env):
        eng, _ = engine_env
        result = eng._execute_plan_tool("enter_plan_mode")
        assert "plan mode" in result.lower()
        assert eng.enforcer.mode == PermissionMode.PLAN

    def test_execute_exit_plan_mode_no_approval(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        result = eng._execute_plan_tool("exit_plan_mode")
        assert "Exited" in result or "restored" in result.lower()

    def test_already_in_plan_mode(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        result = eng._execute_plan_tool("enter_plan_mode")
        assert "Already" in result

    def test_plan_tool_non_string_call_id_gets_fallback_in_transcript(self, engine_env):
        eng, provider = engine_env
        inv = _make_invocation(call_id=["bad"], fn_name="enter_plan_mode", fn_args={})
        comp_tools = _make_completion(text="", invocations=[inv])
        comp_done = _make_completion(text="done")
        provider.generate.side_effect = [comp_tools, comp_done]

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"):
            result = eng.run("Plan this")

        assert result == "done"
        assert any(
            msg.get("role") == "tool" and msg.get("tool_call_id") == "call_0"
            for msg in eng.transcript
        )

    def test_filter_plan_mode_blocks_non_plan_edit(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [("c1", "write_file", {"path": "/other/file.py", "content": "x"})]
        result = eng._filter_plan_mode_calls(calls)
        assert result == []
        # 应在 transcript 中记录被阻止的消息
        blocked = [m for m in eng.transcript if "Blocked" in str(m.get("content", ""))]
        assert len(blocked) > 0

    def test_filter_plan_mode_blocked_edit_uses_call_id_fallback(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [(["bad"], "write_file", {"path": "/other/file.py", "content": "x"})]

        result = eng._filter_plan_mode_calls(calls)

        assert result == []
        assert any(
            msg.get("role") == "tool"
            and msg.get("tool_call_id") == "call_0"
            and "Blocked" in msg.get("content", "")
            for msg in eng.transcript
        )

    def test_filter_plan_mode_blocks_non_object_edit_args(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [("c1", "write_file", ["bad"])]
        result = eng._filter_plan_mode_calls(calls)
        assert result == []
        blocked = [m for m in eng.transcript if "Blocked" in str(m.get("content", ""))]
        assert len(blocked) > 0

    def test_filter_plan_mode_blocks_shell(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [("c2", "shell", {"command": "ls"})]
        result = eng._filter_plan_mode_calls(calls)
        assert result == []

    def test_filter_plan_mode_keeps_non_string_tool_name(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [("c1", ["bad"], {})]

        result = eng._filter_plan_mode_calls(calls)

        assert result == calls

    def test_filter_plan_mode_blocks_malformed_call_shape(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")
        calls = [("c1", "read_file")]

        result = eng._filter_plan_mode_calls(calls)

        assert result == []
        assert any(
            msg.get("role") == "tool" and "Invalid tool call" in msg.get("content", "")
            for msg in eng.transcript
        )

    def test_empty_plan_approval_keeps_planning(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")

        result = eng._handle_approval({}, "Plan")

        assert "keep planning" in result
        assert eng.enforcer.mode == PermissionMode.PLAN

    def test_non_object_plan_approval_keeps_planning(self, engine_env):
        eng, _ = engine_env
        eng._execute_plan_tool("enter_plan_mode")

        result = eng._handle_approval(None, "Plan")

        assert "keep planning" in result
        assert eng.enforcer.mode == PermissionMode.PLAN


# ═══════════════════════════════════════════════════════════════
# 5. 会话持久化
# ═══════════════════════════════════════════════════════════════

class TestCheckpoint:
    def test_save_and_restore(self, engine_env):
        eng, provider = engine_env
        eng.transcript = [{"role": "user", "content": "hello"}]
        path = eng.save_checkpoint()
        assert os.path.isfile(path)

        # 恢复
        saved_id = eng.session_id
        eng.transcript = []
        eng.restore_checkpoint(saved_id)
        assert len(eng.transcript) == 1
        assert eng.transcript[0]["content"] == "hello"

    def test_save_uses_aggregate_token_counts(self, engine_env):
        eng, provider = engine_env
        provider.tokens_used = (10, 5)
        eng._total_input_tokens = 110
        eng._total_output_tokens = 55

        path = eng.save_checkpoint()

        import json
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        assert raw["tokens_in"] == 110
        assert raw["tokens_out"] == 55

    def test_restore_recovers_aggregate_token_counts(self, engine_env):
        eng, provider = engine_env
        eng._total_input_tokens = 110
        eng._total_output_tokens = 55
        saved_id = eng.session_id
        eng.save_checkpoint()

        eng._total_input_tokens = 0
        eng._total_output_tokens = 0
        eng.restore_checkpoint(saved_id)

        assert eng._total_input_tokens == 110
        assert eng._total_output_tokens == 55

    def test_restore_recovers_checkpoint_model(self, engine_env, monkeypatch):
        eng, provider = engine_env
        eng.settings = eng.settings.replace(model="deepseek-chat")
        saved_id = eng.session_id
        eng.save_checkpoint()
        eng.settings = eng.settings.replace(model="qwen3.6-plus")

        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-deepseek"},
        )

        providers = []

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                providers.append(settings)

        monkeypatch.setattr("forgecc.core.engine.Provider", FakeProvider)

        eng.restore_checkpoint(saved_id)

        assert eng.settings.model == "deepseek-chat"
        assert eng.settings.base_url == "https://api.deepseek.com"
        assert eng.provider.settings is eng.settings
        assert providers == [eng.settings]

    def test_restore_can_preserve_current_model_provider(self, engine_env, monkeypatch):
        eng, provider = engine_env
        eng.settings = eng.settings.replace(model="deepseek-chat")
        saved_id = eng.session_id
        eng.save_checkpoint()
        current_settings = eng.settings.replace(
            model="qwen3.6-plus",
            api_key="sk-cli",
            base_url="https://proxy.example/v1",
        )
        eng.settings = current_settings

        monkeypatch.setattr(
            "forgecc.core.engine.Provider",
            lambda settings: pytest.fail("provider should not be rebuilt"),
        )

        eng.restore_checkpoint(saved_id, restore_model=False)

        assert eng.settings is current_settings
        assert eng.provider is provider


# ═══════════════════════════════════════════════════════════════
# 6. 子 Agent 工具过滤
# ═══════════════════════════════════════════════════════════════

class TestSubAgentTools:
    def test_parallel_sub_agents_accept_empty_specs(self, engine_env):
        from forgecc.core.engine import Engine

        result = Engine.execute_sub_agents_parallel([])

        assert result == []

    def test_parallel_sub_agents_report_malformed_specs_as_thread_errors(self, engine_env):
        from forgecc.core.engine import Engine

        result = Engine.execute_sub_agents_parallel(["bad-spec"])

        assert result == [{
            "description": "",
            "result": "(thread error: 'str' object has no attribute 'get')",
            "tokens_in": 0,
            "tokens_out": 0,
        }]

    def test_allowed_tools_intersect_available_tools(self, engine_env):
        from forgecc import toolkit
        from forgecc.core.engine import Engine

        @toolkit.instrument(
            name="read_file",
            description="read",
            parameters={"type": "object", "properties": {}},
            risk_level="read",
        )
        def _read_file():
            return "read"

        @toolkit.instrument(
            name="write_file",
            description="write",
            parameters={"type": "object", "properties": {}},
            risk_level="write",
        )
        def _write_file():
            return "write"

        captured = {}

        def fake_run(self, prompt):
            captured["tool_names"] = self._custom_tool_names
            return "done"

        with patch("forgecc.core.engine.Engine.run", fake_run):
            result = Engine.execute_sub_agent(
                "general",
                "limited task",
                "do it",
                allowed_tools=("read_file", "missing_tool"),
            )

        assert result == "done"
        assert captured["tool_names"] == {"read_file"}

    def test_sub_agent_tool_filter_always_removes_recursive_tools(self, engine_env):
        from forgecc import toolkit
        from forgecc.core.engine import Engine

        for name in ("read_file", "agent", "team"):
            toolkit.instrument(
                name=name,
                description=name,
                parameters={"type": "object", "properties": {}},
                risk_level="read",
            )(lambda: name)

        captured = {}

        def fake_run(self, prompt):
            captured["tool_names"] = self._custom_tool_names
            return "done"

        def fake_config(agent_type):
            return {
                "system_prompt": "custom",
                "tool_names": {"read_file", "agent", "team"},
            }

        with patch("forgecc.core.subagent.get_sub_agent_config", fake_config), \
             patch("forgecc.core.engine.Engine.run", fake_run):
            result = Engine.execute_sub_agent(
                "custom",
                "recursive task",
                "do it",
                allowed_tools=("read_file", "agent", "team"),
            )

        assert result == "done"
        assert captured["tool_names"] == {"read_file"}


# ═══════════════════════════════════════════════════════════════
# 7. 记忆注入
# ═══════════════════════════════════════════════════════════════

class TestMemoryInjection:
    def test_no_prefetch(self, engine_env):
        eng, _ = engine_env
        eng._pending_prefetch = None
        msgs = [{"role": "user", "content": "hi"}]
        result = eng._inject_recalled_memories(msgs)
        assert result == msgs

    def test_inject_recalled(self, engine_env):
        eng, _ = engine_env
        # 模拟已完成的 prefetch
        mem = MagicMock()
        mem.path = "/mem/test.md"
        mem.content = "Memory content"

        future = Future()
        future.set_result([mem])

        pf = MagicMock()
        pf.consumed = False
        pf.settled = True
        pf.future = future

        eng._pending_prefetch = pf

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        result = eng._inject_recalled_memories(msgs)
        # 记忆应被注入到最后的用户消息中
        assert "Memory content" in result[-1]["content"]
        assert pf.consumed is True

    def test_malformed_prefetch_memories_do_not_abort_injection(self, engine_env):
        eng, _ = engine_env
        future = Future()
        future.set_result([{"content": "bad shape"}])

        pf = MagicMock()
        pf.consumed = False
        pf.settled = True
        pf.future = future
        eng._pending_prefetch = pf

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        result = eng._inject_recalled_memories(msgs)

        assert result[-1]["content"] == "hi"
        assert pf.consumed is True

    def test_already_consumed(self, engine_env):
        eng, _ = engine_env
        pf = MagicMock()
        pf.consumed = True
        pf.settled = True
        eng._pending_prefetch = pf

        msgs = [{"role": "user", "content": "hi"}]
        result = eng._inject_recalled_memories(msgs)
        # 不应修改
        assert result[0]["content"] == "hi"


# ═══════════════════════════════════════════════════════════════
# 7. Token 跟踪
# ═══════════════════════════════════════════════════════════════

class TestTokenTracking:
    def test_tokens_accumulated(self, engine_env):
        eng, provider = engine_env
        comp = _make_completion(text="ok", usage_in=100, usage_out=50)
        provider.generate.return_value = comp

        with patch("forgecc.core.engine.maybe_start_memory_prefetch", return_value=None), \
             patch("forgecc.interface.directive.build", return_value="sys"):
            eng.run("hello")

        assert eng._total_input_tokens == 100
        assert eng._total_output_tokens == 50


class TestConversationReset:
    def test_clear_conversation_resets_runtime_state(self, engine_env):
        eng, _ = engine_env
        eng.transcript = [{"role": "user", "content": "old"}]
        eng._round = 3
        eng._collapse = object()
        eng._autocompact_failures[0] = 2
        eng._last_input_tokens = 123
        eng._last_api_call_time = 456.0
        eng._already_surfaced.add("memory.md")
        eng._session_memory_bytes = 789
        eng._pending_prefetch = object()
        eng._context_cleared = True

        eng.clear_conversation()

        assert eng.transcript == []
        assert eng._round == 0
        assert eng._collapse is None
        assert eng._autocompact_failures == [0]
        assert eng._last_input_tokens == 0
        assert eng._last_api_call_time is None
        assert eng._already_surfaced == set()
        assert eng._session_memory_bytes == 0
        assert eng._pending_prefetch is None
        assert eng._context_cleared is False


class TestModelSwitching:
    def test_switch_model_rebuilds_settings_and_provider(self, engine_env, monkeypatch):
        eng, _ = engine_env

        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-deepseek"},
        )

        providers = []

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                providers.append(settings)

        with patch("forgecc.core.engine.Provider", FakeProvider):
            settings = eng.switch_model("deepseek-chat")

        assert settings is eng.settings
        assert settings.model == "deepseek-chat"
        assert settings.api_key == "sk-deepseek"
        assert settings.base_url == "https://api.deepseek.com"
        assert eng.provider.settings is settings
        assert providers == [settings]


class TestManualCompaction:
    def test_compact_conversation_reports_before_after_stats(self, engine_env):
        eng, _ = engine_env
        eng.transcript = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "reply"},
        ]

        from forgecc.core.engine_session import ManualCompactionReport

        compaction_result = MagicMock()
        compaction_result.performed = True
        compaction_result.collapse = object()
        expected_report = ManualCompactionReport(
            result=compaction_result,
            before_messages=2,
            after_messages=2,
            before_tokens=3,
            after_tokens=3,
            context_budget=eng.settings.context_budget,
        )

        with patch("forgecc.core.engine.run_manual_compaction", return_value=expected_report):
            report = eng.compact_conversation()

        assert report is expected_report
        assert report.result is compaction_result
        assert report.before_messages == 2
        assert report.after_messages == 2
        assert report.before_tokens > 0
        assert report.after_tokens > 0
        assert eng._collapse is compaction_result.collapse

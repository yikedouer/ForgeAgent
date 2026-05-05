"""test_repl.py — REPL 技能调用测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forgecc.core.settings import Settings
from forgecc.context.checkpoint import Checkpoint
from forgecc.interface import directive as directive_mod
from forgecc.interface.repl import ForgeREPL, main, _on_tool
from forgecc.skills.playbook import invalidate_cache


@pytest.fixture(autouse=True)
def reset_playbook_cache():
    invalidate_cache()
    yield
    invalidate_cache()


def _write_skill(
    root: Path,
    name: str,
    frontmatter: str,
    body: str = "Do $ARGUMENTS",
) -> None:
    skill_dir = root / ".forgecc" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n{frontmatter}---\n{body}",
        encoding="utf-8",
    )


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.set_plan_approval_fn = MagicMock()
    engine.run = MagicMock(return_value="main result")
    return engine


class TestReplSkillInvocation:
    def test_exit_closes_engine_resources(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)

        assert repl.do_exit("") is True

        engine.close.assert_called_once_with()

    def test_slash_builtin_command_dispatches_to_repl_command(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)
        repl.do_model = MagicMock()

        repl.default("/model qwen3.5-flash")

        repl.do_model.assert_called_once_with("qwen3.5-flash")
        engine.run.assert_not_called()

    def test_slash_builtin_command_trims_leading_whitespace(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)
        repl.do_model = MagicMock()

        repl.default("/ model qwen3.5-flash")

        repl.do_model.assert_called_once_with("qwen3.5-flash")
        engine.run.assert_not_called()

    def test_empty_slash_command_does_not_crash(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)

        repl.default("/")

        engine.run.assert_not_called()

    def test_plain_builtin_command_dispatches_without_cmd_module(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)
        repl.do_usage = MagicMock(return_value=None)

        result = repl.default("usage")

        assert result is None
        repl.do_usage.assert_called_once_with("")
        engine.run.assert_not_called()

    def test_prompt_loop_stops_when_exit_command_returns_true(self):
        engine = _fake_engine()
        repl = ForgeREPL(engine)
        repl._session.prompt = MagicMock(return_value="exit")

        repl.run()

        engine.close.assert_called_once_with()

    def test_inline_skill_runs_resolved_prompt_through_engine(
        self, tmp_path, monkeypatch,
    ):
        _write_skill(tmp_path, "inline", "", "Inline $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        engine = _fake_engine()
        repl = ForgeREPL(engine)

        repl._invoke_skill("/inline task")

        engine.run.assert_called_once()
        assert engine.run.call_args.args[0] == "Inline task"

    def test_slash_skill_still_invokes_skill_when_no_builtin(
        self, tmp_path, monkeypatch,
    ):
        _write_skill(tmp_path, "inline", "", "Inline $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        engine = _fake_engine()
        repl = ForgeREPL(engine)

        repl.default("/inline task")

        engine.run.assert_called_once()
        assert engine.run.call_args.args[0] == "Inline task"

    def test_slash_skill_name_trims_whitespace(
        self, tmp_path, monkeypatch,
    ):
        _write_skill(tmp_path, "inline", "", "Inline $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        engine = _fake_engine()
        repl = ForgeREPL(engine)

        repl._invoke_skill("/ inline task")

        engine.run.assert_called_once()
        assert engine.run.call_args.args[0] == "Inline task"

    def test_fork_skill_invokes_skill_directly(
        self, tmp_path, monkeypatch,
    ):
        _write_skill(tmp_path, "forker", "context: fork\n", "Fork $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        calls = []

        def fake_execute_sub_agent(
            agent_type, description, prompt, model=None, allowed_tools=None,
        ):
            calls.append((agent_type, description, prompt, model, allowed_tools))
            return "fork result"

        monkeypatch.setattr(
            "forgecc.core.engine.Engine.execute_sub_agent",
            staticmethod(fake_execute_sub_agent),
        )

        engine = _fake_engine()
        repl = ForgeREPL(engine)

        repl._invoke_skill("/forker task")

        engine.run.assert_not_called()
        assert calls
        assert calls[0][0] == "general"
        assert "skill:forker" == calls[0][1]
        assert "Fork task" in calls[0][2]


class TestToolCallback:
    def test_non_object_args_do_not_crash_tool_display(self, monkeypatch):
        printed = []

        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(args[0]),
        )

        _on_tool("write_file", ["bad"])

        assert printed
        assert "<invalid args: list>" in printed[0]


class TestReplModelCommand:
    def test_model_switch_delegates_to_engine(self, monkeypatch):
        settings = Settings(
            api_key="sk-qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        engine = _fake_engine()
        engine.settings = settings
        engine.provider = MagicMock()

        def fake_switch_model(model):
            assert model == "deepseek-chat"
            engine.settings = settings.replace(
                api_key="sk-deepseek",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            )
            engine.provider.settings = engine.settings
            return engine.settings

        engine.switch_model = MagicMock(side_effect=fake_switch_model)

        repl = ForgeREPL(engine)

        repl.do_model("deepseek-chat")

        engine.switch_model.assert_called_once_with("deepseek-chat")
        assert engine.settings.model == "deepseek-chat"
        assert engine.settings.api_key == "sk-deepseek"
        assert engine.settings.base_url == "https://api.deepseek.com"
        assert engine.provider.settings is engine.settings


class TestReplExportCommand:
    def test_export_writes_markdown_transcript(self, tmp_path, monkeypatch):
        engine = _fake_engine()
        engine.session_id = "s_export"
        engine.transcript = [
            {"role": "user", "content": "ship the export command"},
            {"role": "assistant", "content": "I will write it."},
            {"role": "tool", "tool_call_id": "tc1", "content": "done"},
        ]
        repl = ForgeREPL(engine)
        output = tmp_path / "conversation.md"
        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(args[0] if args else ""),
        )

        repl.do_export(str(output))

        markdown = output.read_text(encoding="utf-8")
        assert markdown.startswith("# Conversation Export")
        assert "- **Session**: `s_export`" in markdown
        assert "- **Messages**: 3" in markdown
        assert "## 1. User" in markdown
        assert "ship the export command" in markdown
        assert "## 2. Assistant" in markdown
        assert "I will write it." in markdown
        assert "## 3. Tool" in markdown
        assert "done" in markdown
        assert str(output) in printed[-1]


class TestCliOverrides:
    def test_export_command_writes_latest_checkpoint_without_provider(
        self, tmp_path, monkeypatch,
    ):
        output = tmp_path / "latest.md"
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "export", str(output)],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.latest_checkpoint",
            lambda: "latest_session",
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: Checkpoint(
                session_id=session_id,
                messages=[
                    {"role": "user", "content": "offline export"},
                    {"role": "assistant", "content": "ready"},
                ],
                model="qwen3.6-plus",
            ),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: pytest.fail("Settings should not be resolved for export"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )
        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(args[0] if args else ""),
        )

        main()

        markdown = output.read_text(encoding="utf-8")
        assert "- **Session**: `latest_session`" in markdown
        assert "offline export" in markdown
        assert "ready" in markdown
        assert str(output) in printed[-1]

    def test_export_command_can_emit_json_output(
        self, tmp_path, monkeypatch,
    ):
        output = tmp_path / "latest.md"
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "--output-format", "json", "export", str(output)],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.latest_checkpoint",
            lambda: "latest_session",
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: Checkpoint(
                session_id=session_id,
                messages=[{"role": "user", "content": "export json"}],
                model="qwen3.6-plus",
            ),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: pytest.fail("Settings should not be resolved for export"),
        )
        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(args[0] if args else ""),
        )

        main()

        parsed = json.loads(printed[-1])
        assert parsed == {
            "kind": "export",
            "file": str(output),
            "session_id": "latest_session",
            "messages": 1,
        }
        assert "export json" in output.read_text(encoding="utf-8")

    def test_export_command_can_write_jsonl_event_stream(
        self, tmp_path, monkeypatch,
    ):
        output = tmp_path / "latest.jsonl"
        events = [
            {"type": "checkpoint", "session_id": "latest_session", "messages": 1},
            {
                "type": "message",
                "session_id": "latest_session",
                "index": 0,
                "message": {"role": "user", "content": "event export"},
            },
        ]
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "--output-format", "jsonl", "export", str(output)],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.latest_checkpoint",
            lambda: "latest_session",
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load_events",
            lambda session_id: events,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: pytest.fail("Settings should not be resolved for export"),
        )

        main()

        lines = output.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == events

    def test_prompt_can_emit_json_output(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "--output-format", "json", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )

        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(args[0] if args else ""),
        )

        class FakeProvider:
            tokens_used = (0, 0)

            def __init__(self, settings):
                self.settings = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()
                self.session_id = "s-json"
                self._total_input_tokens = 12
                self._total_output_tokens = 34

            def run(self, prompt, on_token=None, on_tool=None):
                assert prompt == "hello"
                assert on_token is None
                assert on_tool is None
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        parsed = json.loads(printed[-1])
        assert parsed == {
            "kind": "response",
            "message": "done",
            "model": "qwen3.6-plus",
            "session_id": "s-json",
            "usage": {"input_tokens": 12, "output_tokens": 34},
        }

    def test_blank_resume_arg_is_rejected_before_loading_checkpoint(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-r", "   ", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: pytest.fail("checkpoint should not be loaded"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1

    def test_resume_latest_resolves_most_recent_checkpoint_before_loading(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-r", "latest", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.latest_checkpoint",
            lambda: "newer",
            raising=False,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: Checkpoint(
                session_id=session_id,
                messages=[],
                model="qwen3.6-plus",
            ),
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()

            def restore_checkpoint(self, session_id, *, restore_model=True):
                built["restored"] = session_id
                built["restore_model"] = restore_model

            def run(self, prompt, on_token=None, on_tool=None):
                built["prompt"] = prompt
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        assert built["restored"] == "newer"
        assert built["restore_model"] is False
        assert built["prompt"] == "hello"

    def test_prompt_mode_closes_engine_before_returning(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr("sys.argv", ["forgecc", "-p", "hello"])
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                self.tokens_used = (0, 0)

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()
                self.close = MagicMock()
                built["engine"] = self

            def run(self, prompt, on_token=None, on_tool=None):
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        built["engine"].close.assert_called_once_with()

    def test_resume_arg_reinfers_saved_model_before_api_key_check(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-r", "saved", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-deepseek"},
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: Checkpoint(
                session_id=session_id,
                messages=[],
                model="deepseek-chat",
            ),
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                built["provider_settings"] = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()
                built["engine_settings"] = settings

            def restore_checkpoint(self, session_id, *, restore_model=True):
                built["restored"] = session_id
                built["restore_model"] = restore_model

            def run(self, prompt, on_token=None, on_tool=None):
                built["prompt"] = prompt
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        settings = built["engine_settings"]
        assert settings.model == "deepseek-chat"
        assert settings.api_key == "sk-deepseek"
        assert settings.base_url == "https://api.deepseek.com"
        assert built["provider_settings"] is settings
        assert built["restored"] == "saved"
        assert built["restore_model"] is False
        assert built["prompt"] == "hello"


class TestDirectiveBuild:
    def test_git_branch_is_read_from_settings_workspace(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        settings = Settings(
            api_key="sk-test",
            base_url="https://example.test",
            model="test-model",
            context_budget=100,
            max_rounds=3,
            workspace=str(workspace),
            permission_mode="prompt",
        )

        calls = []

        def fake_check_output(args, **kwargs):
            calls.append((args, kwargs))
            if kwargs.get("cwd") != str(workspace):
                raise AssertionError("git branch must be read from settings.workspace")
            return "feature/workspace\n"

        monkeypatch.setattr(directive_mod.subprocess, "check_output", fake_check_output)
        monkeypatch.setattr(directive_mod, "_project_rules", lambda workspace: "")
        monkeypatch.setattr(directive_mod, "_tool_manifest", lambda: "")
        monkeypatch.setattr(directive_mod, "_memory_section", lambda workspace: "")
        monkeypatch.setattr(directive_mod.playbook, "describe_for_directive", lambda: "")
        monkeypatch.setattr(directive_mod, "build_agent_descriptions", lambda: "")

        result = directive_mod.build(settings)

        assert "Git branch: feature/workspace" in result
        assert calls

    def test_resume_preserves_explicit_endpoint_overrides(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "forgecc",
                "-r", "saved",
                "--base-url", "https://proxy.example/v1",
                "--api-key", "sk-proxy",
                "-p", "hello",
            ],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {},
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.ckpt.load",
            lambda session_id: Checkpoint(
                session_id=session_id,
                messages=[],
                model="deepseek-chat",
            ),
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                built["provider_settings"] = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()
                built["engine_settings"] = settings

            def restore_checkpoint(self, session_id, *, restore_model=True):
                built["restored"] = session_id
                built["restore_model"] = restore_model

            def run(self, prompt, on_token=None, on_tool=None):
                built["prompt"] = prompt
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        settings = built["engine_settings"]
        assert settings.model == "deepseek-chat"
        assert settings.api_key == "sk-proxy"
        assert settings.base_url == "https://proxy.example/v1"
        assert settings.client_type == "openai"
        assert settings.api_version == ""
        assert built["provider_settings"] is settings
        assert built["restored"] == "saved"
        assert built["restore_model"] is False
        assert built["prompt"] == "hello"

    def test_model_arg_reinfers_provider_before_building_engine(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="sk-qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-m", "deepseek-chat", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-deepseek"},
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                self.settings = settings
                built["provider_settings"] = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.settings = settings
                self.provider = provider
                self.enforcer = MagicMock()
                built["engine_settings"] = settings

            def run(self, prompt, on_token=None, on_tool=None):
                built["prompt"] = prompt
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        settings = built["engine_settings"]
        assert settings.model == "deepseek-chat"
        assert settings.api_key == "sk-deepseek"
        assert settings.base_url == "https://api.deepseek.com"
        assert built["provider_settings"] is settings
        assert built["prompt"] == "hello"

    def test_blank_model_arg_is_rejected(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-m", "   ", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1

    def test_blank_api_key_arg_is_rejected(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "--api-key", "   ", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1

    def test_blank_base_url_arg_is_rejected(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "--base-url", "   ", "-p", "hello"],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1

    def test_blank_prompt_arg_is_rejected(self, monkeypatch):
        base_settings = Settings(
            api_key="sk-env",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.6-plus",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["forgecc", "-p", "   "],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Provider",
            lambda settings: pytest.fail("Provider should not be constructed"),
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Engine",
            lambda settings, provider: pytest.fail("Engine should not be constructed"),
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1

    def test_base_url_arg_forces_openai_compatible_client(
        self, monkeypatch,
    ):
        base_settings = Settings(
            api_key="sk-azure",
            base_url="https://iai.alibaba-inc.com/azure",
            model="gpt-4.1-0414",
            context_budget=128000,
            max_rounds=60,
            workspace="/tmp/work",
            permission_mode="prompt",
            client_type="azure",
            api_version="2024-12-01-preview",
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "forgecc",
                "-m", "gpt-4o",
                "--base-url", "https://api.openai.com/v1",
                "--api-key", "sk-openai",
                "-p", "hello",
            ],
        )
        monkeypatch.setattr(
            "forgecc.interface.repl.Settings.resolve",
            lambda: base_settings,
        )
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"AZURE_API_KEY": "sk-azure"},
        )

        built = {}

        class FakeProvider:
            def __init__(self, settings):
                built["provider_settings"] = settings

        class FakeEngine:
            def __init__(self, settings, provider):
                self.enforcer = MagicMock()
                built["engine_settings"] = settings

            def run(self, prompt, on_token=None, on_tool=None):
                return "done"

        monkeypatch.setattr("forgecc.interface.repl.Provider", FakeProvider)
        monkeypatch.setattr("forgecc.interface.repl.Engine", FakeEngine)

        main()

        settings = built["engine_settings"]
        assert settings.model == "gpt-4o"
        assert settings.api_key == "sk-openai"
        assert settings.base_url == "https://api.openai.com/v1"
        assert settings.client_type == "openai"
        assert settings.api_version == ""


class TestReplUsage:
    def test_usage_uses_engine_aggregate_tokens(self, monkeypatch):
        engine = _fake_engine()
        engine.provider.tokens_used = (10, 5)
        engine._total_input_tokens = 110
        engine._total_output_tokens = 55
        repl = ForgeREPL(engine)

        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(str(args[0])),
        )

        repl.do_usage("")

        assert any("110" in line and "55" in line for line in printed)

    def test_cost_uses_engine_aggregate_tokens(self, monkeypatch):
        engine = _fake_engine()
        engine.provider.tokens_used = (10, 5)
        engine._total_input_tokens = 110
        engine._total_output_tokens = 55
        repl = ForgeREPL(engine)

        printed = []
        monkeypatch.setattr(
            "forgecc.interface.repl.console.print",
            lambda *args, **kwargs: printed.append(str(args[0])),
        )

        repl.do_cost("")

        assert any("110" in line for line in printed)
        assert any("55" in line for line in printed)

"""test_settings.py — 设置加载测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forgecc.core.settings import Settings, _parse_dotenv, _load_env_cascade


# ═══════════════════════════════════════════════════════════
# 3.1 _parse_dotenv
# ═══════════════════════════════════════════════════════════

class TestParseDotenv:
    def test_basic_key_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY=VALUE\n")
        assert _parse_dotenv(f) == {"KEY": "VALUE"}

    def test_export_key_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("export KEY=VALUE\n")
        assert _parse_dotenv(f) == {"KEY": "VALUE"}

    def test_export_key_value_with_tab_separator(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("export\tKEY=VALUE\n")
        assert _parse_dotenv(f) == {"KEY": "VALUE"}

    def test_quoted_double(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('KEY="hello world"\n')
        assert _parse_dotenv(f) == {"KEY": "hello world"}

    def test_quoted_double_with_inline_comment(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('KEY="hello world" # local override\n')
        assert _parse_dotenv(f) == {"KEY": "hello world"}

    def test_quoted_double_preserves_hash_inside_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('KEY="hello # world" # local override\n')
        assert _parse_dotenv(f) == {"KEY": "hello # world"}

    def test_quoted_single(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY='hello world'\n")
        assert _parse_dotenv(f) == {"KEY": "hello world"}

    def test_comment_line(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# this is a comment\nKEY=VAL\n")
        assert _parse_dotenv(f) == {"KEY": "VAL"}

    def test_inline_comment_after_unquoted_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY=VAL # local override\n")
        assert _parse_dotenv(f) == {"KEY": "VAL"}

    def test_inline_comment_after_tab_unquoted_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY=VAL\t# local override\n")
        assert _parse_dotenv(f) == {"KEY": "VAL"}

    def test_empty_lines_skipped(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("\n\nKEY=VAL\n\n")
        assert _parse_dotenv(f) == {"KEY": "VAL"}

    def test_no_equals_skipped(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("THIS_HAS_NO_EQUALS\nKEY=VAL\n")
        assert _parse_dotenv(f) == {"KEY": "VAL"}

    def test_file_not_exist(self, tmp_path):
        f = tmp_path / "nonexistent"
        assert _parse_dotenv(f) == {}

    def test_multiple_entries(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("A=1\nB=2\nC=3\n")
        result = _parse_dotenv(f)
        assert result == {"A": "1", "B": "2", "C": "3"}


class TestLoadEnvCascade:
    def test_project_env_is_loaded_from_configured_workspace(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        other = tmp_path / "other"
        (home / ".forgecc").mkdir(parents=True)
        workspace.mkdir()
        other.mkdir()
        (home / ".forgecc" / ".env").write_text(
            f"FORGECC_WORKSPACE={workspace}\n",
            encoding="utf-8",
        )
        (workspace / ".env").write_text(
            "FORGECC_MODEL=deepseek-chat\nDEEPSEEK_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(other)
        for key in ("FORGECC_WORKSPACE", "FORGECC_MODEL", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGECC_WORKSPACE"] == str(workspace)
        assert env["FORGECC_MODEL"] == "deepseek-chat"
        assert env["DEEPSEEK_API_KEY"] == "sk-workspace"

    def test_workspace_env_path_expands_user_before_loading_project_env(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        workspace = home / "workspace"
        other = tmp_path / "other"
        (home / ".forgecc").mkdir(parents=True)
        workspace.mkdir(parents=True)
        other.mkdir()
        (home / ".forgecc" / ".env").write_text(
            "FORGECC_WORKSPACE=~/workspace\n",
            encoding="utf-8",
        )
        (workspace / ".env").write_text(
            "FORGECC_MODEL=deepseek-chat\nDEEPSEEK_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(other)
        for key in ("FORGECC_WORKSPACE", "FORGECC_MODEL", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGECC_WORKSPACE"] == "~/workspace"
        assert env["FORGECC_MODEL"] == "deepseek-chat"
        assert env["DEEPSEEK_API_KEY"] == "sk-workspace"

    def test_blank_workspace_environment_loads_current_project_env(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (home / ".forgecc").mkdir(parents=True)
        (workspace / ".env").write_text(
            "FORGECC_MODEL=deepseek-chat\nDEEPSEEK_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("FORGECC_WORKSPACE", "   ")
        for key in ("FORGECC_MODEL", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGECC_MODEL"] == "deepseek-chat"
        assert env["DEEPSEEK_API_KEY"] == "sk-workspace"


# ═══════════════════════════════════════════════════════════
# 3.3 Settings.resolve (需要隔离环境变量)
# ═══════════════════════════════════════════════════════════

class TestSettingsResolve:
    def test_default_model(self, monkeypatch):
        # 清空影响的环境变量
        for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "FORGECC_MODEL",
                   "FORGECC_CTX_BUDGET", "FORGECC_MAX_ROUNDS",
                   "FORGECC_WORKSPACE", "FORGECC_PERMISSION_MODE",
                   "DEEPSEEK_API_KEY", "QWEN_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        # 屏蔽 .env 文件影响，确保测试拿到纯默认值
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade", lambda: {}
        )
        s = Settings.resolve()
        assert s.model == "qwen3.6-plus"
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_env_override(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "FORGECC_PROVIDER": "openai",
                     "FORGECC_MODEL": "gpt-4",
                     "FORGECC_CTX_BUDGET": "64000"},
        )
        s = Settings.resolve()
        assert s.api_key == "sk-test"
        assert s.model == "gpt-4"
        assert s.context_budget == 64000

    def test_hook_paths_are_parsed_from_env(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_HOOKS": " hooks/a.py : hooks/b.py "},
        )

        s = Settings.resolve()

        assert s.hook_paths == ("hooks/a.py", "hooks/b.py")

    def test_mcp_servers_are_parsed_from_env(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {
                "FORGECC_MCP_SERVERS": """
                {
                  "filesystem": {
                    "command": "uvx",
                    "args": ["mcp-server-filesystem", "/tmp"]
                  }
                }
                """,
            },
        )

        s = Settings.resolve()

        assert len(s.mcp_servers) == 1
        assert s.mcp_servers[0].name == "filesystem"
        assert s.mcp_servers[0].command == "uvx"
        assert s.mcp_servers[0].args == ("mcp-server-filesystem", "/tmp")

    def test_invalid_numeric_settings_use_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_CTX_BUDGET": "many",
                     "FORGECC_MAX_ROUNDS": "often"},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_non_positive_numeric_settings_use_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_CTX_BUDGET": "0",
                     "FORGECC_MAX_ROUNDS": "-1"},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_boolean_numeric_settings_use_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_CTX_BUDGET": True,
                     "FORGECC_MAX_ROUNDS": True},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_permission_mode_is_normalized(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_PERMISSION_MODE": " DANGER "},
        )
        s = Settings.resolve()
        assert s.permission_mode == "danger"

    def test_invalid_permission_mode_uses_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_PERMISSION_MODE": "oops"},
        )
        s = Settings.resolve()
        assert s.permission_mode == "prompt"

    def test_non_string_permission_mode_uses_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_PERMISSION_MODE": ["danger"]},
        )
        s = Settings.resolve()
        assert s.permission_mode == "prompt"

    def test_workspace_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_WORKSPACE": "~/project"},
        )

        s = Settings.resolve()

        assert s.workspace == str(home / "project")

    def test_non_string_workspace_uses_current_directory(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_WORKSPACE": ["~/project"]},
        )

        s = Settings.resolve()

        assert s.workspace == str(tmp_path)

    def test_blank_workspace_uses_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_WORKSPACE": "   "},
        )

        s = Settings.resolve()

        assert s.workspace == str(tmp_path)

    def test_deepseek_preset(self, monkeypatch):
        """模型名以 deepseek 开头时自动推断 DeepSeek 服务商。"""
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-ds-test",
                     "FORGECC_MODEL": "deepseek-chat"},
        )
        s = Settings.resolve()
        assert s.model == "deepseek-chat"
        assert s.api_key == "sk-ds-test"
        assert s.base_url == "https://api.deepseek.com"

    def test_qwen_preset(self, monkeypatch):
        """模型名以 qwen 开头时自动推断 Qwen 服务商。"""
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw-test",
                     "FORGECC_MODEL": "qwen3.6-plus"},
        )
        s = Settings.resolve()
        assert s.model == "qwen3.6-plus"
        assert s.api_key == "sk-qw-test"
        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_provider_api_key_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": " sk-qw-test ",
                     "FORGECC_MODEL": "qwen3.6-plus"},
        )

        s = Settings.resolve()

        assert s.api_key == "sk-qw-test"

    def test_non_string_openai_base_url_uses_provider_default(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw-test",
                     "FORGECC_MODEL": "qwen3.6-plus",
                     "OPENAI_BASE_URL": ["https://proxy.example"]},
        )

        s = Settings.resolve()

        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_openai_base_url_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw-test",
                     "FORGECC_PROVIDER": "qwen",
                     "OPENAI_BASE_URL": " https://proxy.example/v1 "},
        )

        s = Settings.resolve()

        assert s.base_url == "https://proxy.example/v1"

    def test_azure_api_version_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"AZURE_API_KEY": "sk-az-test",
                     "FORGECC_PROVIDER": "azure",
                     "AZURE_API_VERSION": " 2024-12-01-preview "},
        )

        s = Settings.resolve()

        assert s.api_version == "2024-12-01-preview"

    def test_unknown_provider_non_string_openai_base_url_uses_default(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_PROVIDER": "custom",
                     "FORGECC_MODEL": "custom-model",
                     "OPENAI_BASE_URL": ["https://proxy.example"]},
        )

        s = Settings.resolve()

        assert s.base_url == "https://api.openai.com/v1"

    def test_model_name_trims_whitespace_before_provider_infer(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-ds-test",
                     "FORGECC_MODEL": " deepseek-chat "},
        )
        s = Settings.resolve()
        assert s.model == "deepseek-chat"
        assert s.api_key == "sk-ds-test"
        assert s.base_url == "https://api.deepseek.com"

    def test_non_string_model_uses_default_model(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"FORGECC_MODEL": ["deepseek-chat"]},
        )

        s = Settings.resolve()

        assert s.model == "qwen3.6-plus"
        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_explicit_provider_overrides_model_infer(self, monkeypatch):
        """显式设置 FORGECC_PROVIDER 优先于模型名推断。

        场景：用 Qwen 服务商代理跑 DeepSeek 模型。
        """
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw-proxy",
                     "FORGECC_PROVIDER": "qwen",
                     "FORGECC_MODEL": "deepseek-chat"},
        )
        s = Settings.resolve()
        assert s.model == "deepseek-chat"  # 模型名透传
        assert s.api_key == "sk-qw-proxy"  # 用 Qwen 的 key
        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"  # Qwen 的地址

    def test_explicit_provider_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw-proxy",
                     "FORGECC_PROVIDER": " qwen ",
                     "FORGECC_MODEL": "deepseek-chat"},
        )
        s = Settings.resolve()
        assert s.model == "deepseek-chat"
        assert s.api_key == "sk-qw-proxy"
        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_blank_provider_uses_model_inference(self, monkeypatch):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-ds-test",
                     "FORGECC_PROVIDER": "   ",
                     "FORGECC_MODEL": "deepseek-chat"},
        )

        s = Settings.resolve()

        assert s.model == "deepseek-chat"
        assert s.api_key == "sk-ds-test"
        assert s.base_url == "https://api.deepseek.com"

    def test_provider_only_uses_default_model(self, monkeypatch):
        """只设置 FORGECC_PROVIDER 未设置模型时使用服务商默认模型。"""
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-ds",
                     "FORGECC_PROVIDER": "deepseek"},
        )
        s = Settings.resolve()
        assert s.model == "deepseek-chat"  # DeepSeek 默认模型
        assert s.base_url == "https://api.deepseek.com"

    def test_same_provider_switch_model(self, monkeypatch):
        """同一服务商内切换模型——只改 FORGECC_MODEL 就行。"""
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": "sk-qw",
                     "FORGECC_PROVIDER": "qwen",
                     "FORGECC_MODEL": "qwen3.5-plus"},
        )
        s = Settings.resolve()
        assert s.model == "qwen3.5-plus"
        assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_fallback_to_openai_key(self, monkeypatch):
        """专属 key 不存在时回退到 OPENAI_API_KEY。"""
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-fallback",
                     "FORGECC_MODEL": "deepseek-chat"},
        )
        s = Settings.resolve()
        assert s.api_key == "sk-fallback"

    def test_non_string_provider_key_falls_back_to_openai_key(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"QWEN_API_KEY": ["sk-qw"],
                     "OPENAI_API_KEY": "sk-fallback",
                     "FORGECC_MODEL": "qwen3.6-plus"},
        )

        s = Settings.resolve()

        assert s.api_key == "sk-fallback"


# ═══════════════════════════════════════════════════════════
# 3.4 Settings.replace
# ═══════════════════════════════════════════════════════════

class TestSettingsReplace:
    def test_replace_creates_new_instance(self, mock_settings):
        new = mock_settings.replace(model="gpt-5")
        assert new.model == "gpt-5"
        assert mock_settings.model == "test-model"
        assert new is not mock_settings

    def test_replace_preserves_other_fields(self, mock_settings):
        new = mock_settings.replace(model="gpt-5")
        assert new.api_key == mock_settings.api_key
        assert new.context_budget == mock_settings.context_budget

    def test_replace_preserves_mcp_server_config_objects(self, mock_settings):
        from forgecc.core.mcp import MCPServerConfig

        server = MCPServerConfig(name="fs", command="uvx")
        settings = mock_settings.replace(mcp_servers=(server,))

        new = settings.replace(model="gpt-5")

        assert new.mcp_servers == (server,)
        assert isinstance(new.mcp_servers[0], MCPServerConfig)


class TestSettingsForModel:
    def test_for_model_trims_model_before_provider_infer(
        self, monkeypatch, mock_settings,
    ):
        monkeypatch.setattr(
            "forgecc.core.settings._load_env_cascade",
            lambda: {"DEEPSEEK_API_KEY": "sk-ds-test"},
        )

        new = mock_settings.for_model(" deepseek-chat ")

        assert new.model == "deepseek-chat"
        assert new.api_key == "sk-ds-test"
        assert new.base_url == "https://api.deepseek.com"

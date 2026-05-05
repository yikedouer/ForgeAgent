"""test_settings.py — 设置加载测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forgeagent.core.settings import Settings, _parse_dotenv, _load_env_cascade


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
        (home / ".forgeagent").mkdir(parents=True)
        workspace.mkdir()
        other.mkdir()
        (home / ".forgeagent" / ".env").write_text(
            f"FORGEAGENT_WORKSPACE={workspace}\n",
            encoding="utf-8",
        )
        (workspace / ".env").write_text(
            "MODEL=custom-model\nOPENAI_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(other)
        for key in ("FORGEAGENT_WORKSPACE", "MODEL", "OPENAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGEAGENT_WORKSPACE"] == str(workspace)
        assert env["MODEL"] == "custom-model"
        assert env["OPENAI_API_KEY"] == "sk-workspace"

    def test_workspace_env_path_expands_user_before_loading_project_env(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        workspace = home / "workspace"
        other = tmp_path / "other"
        (home / ".forgeagent").mkdir(parents=True)
        workspace.mkdir(parents=True)
        other.mkdir()
        (home / ".forgeagent" / ".env").write_text(
            "FORGEAGENT_WORKSPACE=~/workspace\n",
            encoding="utf-8",
        )
        (workspace / ".env").write_text(
            "FORGEAGENT_MODEL=custom-model\nOPENAI_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(other)
        for key in ("FORGEAGENT_WORKSPACE", "FORGEAGENT_MODEL", "OPENAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGEAGENT_WORKSPACE"] == "~/workspace"
        assert env["FORGEAGENT_MODEL"] == "custom-model"
        assert env["OPENAI_API_KEY"] == "sk-workspace"

    def test_blank_workspace_environment_loads_current_project_env(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (home / ".forgeagent").mkdir(parents=True)
        (workspace / ".env").write_text(
            "FORGEAGENT_MODEL=custom-model\nOPENAI_API_KEY=sk-workspace\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("FORGEAGENT_WORKSPACE", "   ")
        for key in ("FORGEAGENT_MODEL", "OPENAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        env = _load_env_cascade()

        assert env["FORGEAGENT_MODEL"] == "custom-model"
        assert env["OPENAI_API_KEY"] == "sk-workspace"


# ═══════════════════════════════════════════════════════════
# 3.3 Settings.resolve (需要隔离环境变量)
# ═══════════════════════════════════════════════════════════

class TestSettingsResolve:
    def test_default_model(self, monkeypatch):
        # 清空影响的环境变量
        for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL", "FORGEAGENT_MODEL",
                   "FORGEAGENT_CTX_BUDGET", "FORGEAGENT_MAX_ROUNDS",
                   "FORGEAGENT_WORKSPACE", "FORGEAGENT_PERMISSION_MODE",
                   "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        # 屏蔽 .env 文件影响，确保测试拿到纯默认值
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade", lambda: {}
        )
        s = Settings.resolve()
        assert s.model == "gpt-4o"
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_env_override(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "MODEL": "gpt-4",
                     "FORGEAGENT_CTX_BUDGET": "64000"},
        )
        s = Settings.resolve()
        assert s.api_key == "sk-test"
        assert s.model == "gpt-4"
        assert s.context_budget == 64000

    def test_hook_paths_are_parsed_from_env(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_HOOKS": " hooks/a.py : hooks/b.py "},
        )

        s = Settings.resolve()

        assert s.hook_paths == ("hooks/a.py", "hooks/b.py")

    def test_mcp_servers_are_parsed_from_env(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {
                "FORGEAGENT_MCP_SERVERS": """
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
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_CTX_BUDGET": "many",
                     "FORGEAGENT_MAX_ROUNDS": "often"},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_non_positive_numeric_settings_use_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_CTX_BUDGET": "0",
                     "FORGEAGENT_MAX_ROUNDS": "-1"},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_boolean_numeric_settings_use_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_CTX_BUDGET": True,
                     "FORGEAGENT_MAX_ROUNDS": True},
        )
        s = Settings.resolve()
        assert s.context_budget == 128000
        assert s.max_rounds == 60

    def test_permission_mode_is_normalized(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_PERMISSION_MODE": " DANGER "},
        )
        s = Settings.resolve()
        assert s.permission_mode == "danger"

    def test_invalid_permission_mode_uses_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_PERMISSION_MODE": "oops"},
        )
        s = Settings.resolve()
        assert s.permission_mode == "prompt"

    def test_non_string_permission_mode_uses_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_PERMISSION_MODE": ["danger"]},
        )
        s = Settings.resolve()
        assert s.permission_mode == "prompt"

    def test_workspace_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_WORKSPACE": "~/project"},
        )

        s = Settings.resolve()

        assert s.workspace == str(home / "project")

    def test_non_string_workspace_uses_current_directory(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_WORKSPACE": ["~/project"]},
        )

        s = Settings.resolve()

        assert s.workspace == str(tmp_path)

    def test_blank_workspace_uses_current_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_WORKSPACE": "   "},
        )

        s = Settings.resolve()

        assert s.workspace == str(tmp_path)

    def test_openai_compatible_endpoint_from_env(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "OPENAI_BASE_URL": "https://proxy.example/v1",
                     "FORGEAGENT_MODEL": "custom-model"},
        )
        s = Settings.resolve()
        assert s.model == "custom-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://proxy.example/v1"

    def test_model_name_does_not_infer_provider(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "FORGEAGENT_MODEL": "provider-looking-model"},
        )
        s = Settings.resolve()
        assert s.model == "provider-looking-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_openai_api_key_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": " sk-test "},
        )

        s = Settings.resolve()

        assert s.api_key == "sk-test"

    def test_non_string_openai_base_url_uses_openai_default(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "OPENAI_BASE_URL": ["https://proxy.example"]},
        )

        s = Settings.resolve()

        assert s.base_url == "https://api.openai.com/v1"

    def test_openai_base_url_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_BASE_URL": " https://proxy.example/v1 "},
        )

        s = Settings.resolve()

        assert s.base_url == "https://proxy.example/v1"

    def test_unknown_env_keys_do_not_change_endpoint(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"SOME_PROVIDER": "legacy",
                     "OPENAI_API_KEY": "sk-test",
                     "FORGEAGENT_MODEL": "custom-model"},
        )

        s = Settings.resolve()

        assert s.api_key == "sk-test"
        assert s.model == "custom-model"
        assert s.base_url == "https://api.openai.com/v1"

    def test_model_name_trims_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "FORGEAGENT_MODEL": " custom-model "},
        )
        s = Settings.resolve()
        assert s.model == "custom-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_non_string_model_uses_default_model(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"FORGEAGENT_MODEL": ["custom-model"]},
        )

        s = Settings.resolve()

        assert s.model == "gpt-4o"
        assert s.base_url == "https://api.openai.com/v1"

    def test_endpoint_defaults_when_only_model_and_key_are_set(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "FORGEAGENT_MODEL": "custom-model"},
        )
        s = Settings.resolve()
        assert s.model == "custom-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_model_whitespace_does_not_change_endpoint(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "FORGEAGENT_MODEL": " custom-model "},
        )
        s = Settings.resolve()
        assert s.model == "custom-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_blank_extra_provider_like_key_is_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "SOME_PROVIDER": "   ",
                     "FORGEAGENT_MODEL": "custom-model"},
        )

        s = Settings.resolve()

        assert s.model == "custom-model"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_api_key_only_uses_default_model(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test"},
        )
        s = Settings.resolve()
        assert s.model == "gpt-4o"
        assert s.api_key == "sk-test"
        assert s.base_url == "https://api.openai.com/v1"

    def test_same_endpoint_switch_model(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-test",
                     "OPENAI_BASE_URL": "https://proxy.example/v1",
                     "FORGEAGENT_MODEL": "smaller-model"},
        )
        s = Settings.resolve()
        assert s.model == "smaller-model"
        assert s.base_url == "https://proxy.example/v1"

    def test_openai_key_is_used_for_any_model(self, monkeypatch):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-fallback",
                     "FORGEAGENT_MODEL": "custom-model"},
        )
        s = Settings.resolve()
        assert s.api_key == "sk-fallback"

    def test_non_openai_key_is_ignored(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"CUSTOM_API_KEY": "sk-provider-specific",
                     "OPENAI_API_KEY": "sk-fallback",
                     "FORGEAGENT_MODEL": "custom-model"},
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
        from forgeagent.core.mcp import MCPServerConfig

        server = MCPServerConfig(name="fs", command="uvx")
        settings = mock_settings.replace(mcp_servers=(server,))

        new = settings.replace(model="gpt-5")

        assert new.mcp_servers == (server,)
        assert isinstance(new.mcp_servers[0], MCPServerConfig)


class TestSettingsForModel:
    def test_for_model_trims_model_and_reuses_endpoint(
        self, monkeypatch, mock_settings,
    ):
        monkeypatch.setattr(
            "forgeagent.core.settings._load_env_cascade",
            lambda: {"OPENAI_API_KEY": "sk-other"},
        )

        new = mock_settings.for_model(" custom-model ")

        assert new.model == "custom-model"
        assert new.api_key == mock_settings.api_key
        assert new.base_url == mock_settings.base_url

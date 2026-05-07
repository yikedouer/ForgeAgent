"""Settings loading tests."""

from __future__ import annotations

import os
from pathlib import Path

from forgeagent.core.mcp import MCPServerConfig
from forgeagent.core.settings import Settings, _load_env_cascade, _parse_dotenv


def _resolve(monkeypatch, env: dict[str, object], cwd: Path | None = None) -> Settings:
    if cwd is not None:
        monkeypatch.chdir(cwd)
    monkeypatch.setattr("forgeagent.core.settings._load_env_cascade", lambda: env)
    return Settings.resolve()


def test_parse_dotenv_syntax(tmp_path):
    cases = [
        ("KEY=VALUE\n", {"KEY": "VALUE"}),
        ("export KEY=VALUE\n", {"KEY": "VALUE"}),
        ("export\tKEY=VALUE\n", {"KEY": "VALUE"}),
        ('KEY="hello world" # local override\n', {"KEY": "hello world"}),
        ('KEY="hello # world" # local override\n', {"KEY": "hello # world"}),
        ("KEY='hello world'\n", {"KEY": "hello world"}),
        ("# comment\nKEY=VAL\n", {"KEY": "VAL"}),
        ("KEY=VAL # local override\n", {"KEY": "VAL"}),
        ("KEY=VAL\t# local override\n", {"KEY": "VAL"}),
        ("\nTHIS_HAS_NO_EQUALS\nKEY=VAL\n\n", {"KEY": "VAL"}),
        ("A=1\nB=2\nC=3\n", {"A": "1", "B": "2", "C": "3"}),
    ]

    for index, (content, expected) in enumerate(cases):
        path = tmp_path / f".env.{index}"
        path.write_text(content, encoding="utf-8")
        assert _parse_dotenv(path) == expected

    assert _parse_dotenv(tmp_path / "missing.env") == {}


def test_load_env_cascade_uses_user_workspace_project_and_real_env(tmp_path, monkeypatch):
    env_keys = (
        "FORGEAGENT_WORKSPACE",
        "MODEL",
        "FORGEAGENT_MODEL",
        "OPENAI_API_KEY",
    )

    home = tmp_path / "home"
    workspace = home / "workspace"
    other = tmp_path / "other"
    (home / ".forgeagent").mkdir(parents=True)
    workspace.mkdir(parents=True)
    other.mkdir()
    (home / ".forgeagent" / ".env").write_text(
        "FORGEAGENT_WORKSPACE=~/workspace\nMODEL=user-model\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        "MODEL=project-model\nOPENAI_API_KEY=sk-project\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(other)
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)

    env = _load_env_cascade()
    assert env["FORGEAGENT_WORKSPACE"] == "~/workspace"
    assert env["MODEL"] == "project-model"
    assert env["OPENAI_API_KEY"] == "sk-project"

    monkeypatch.setenv("MODEL", "real-model")
    assert _load_env_cascade()["MODEL"] == "real-model"

    monkeypatch.setenv("FORGEAGENT_WORKSPACE", "   ")
    assert _load_env_cascade()["MODEL"] == "real-model"


def test_resolve_defaults_and_core_overrides(tmp_path, monkeypatch):
    settings = _resolve(monkeypatch, {}, cwd=tmp_path)
    assert settings.model == "gpt-4o"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.context_budget == 128000
    assert settings.max_rounds == 60
    assert settings.workspace == str(tmp_path)
    assert settings.permission_mode == "prompt"

    settings = _resolve(
        monkeypatch,
        {
            "OPENAI_API_KEY": " sk-test ",
            "OPENAI_BASE_URL": " https://proxy.example/v1 ",
            "MODEL": " custom-model ",
            "FORGEAGENT_CTX_BUDGET": "64000",
            "FORGEAGENT_MAX_ROUNDS": "12",
            "FORGEAGENT_PERMISSION_MODE": " DANGER ",
        },
    )
    assert settings.api_key == "sk-test"
    assert settings.base_url == "https://proxy.example/v1"
    assert settings.model == "custom-model"
    assert settings.context_budget == 64000
    assert settings.max_rounds == 12
    assert settings.permission_mode == "danger"


def test_resolve_keeps_openai_compatible_provider_contract(monkeypatch):
    cases = [
        (
            {"OPENAI_API_KEY": "sk-test", "FORGEAGENT_MODEL": "legacy-model"},
            ("sk-test", "https://api.openai.com/v1", "legacy-model"),
        ),
        (
            {"OPENAI_API_KEY": "sk-test", "MODEL": "model", "FORGEAGENT_MODEL": "legacy"},
            ("sk-test", "https://api.openai.com/v1", "model"),
        ),
        (
            {"OPENAI_API_KEY": "sk-test", "MODEL": ["bad-model"]},
            ("sk-test", "https://api.openai.com/v1", "gpt-4o"),
        ),
        (
            {"CUSTOM_API_KEY": "sk-private", "OPENAI_API_KEY": "sk-openai", "MODEL": "model"},
            ("sk-openai", "https://api.openai.com/v1", "model"),
        ),
        (
            {"SOME_PROVIDER": "legacy", "OPENAI_API_KEY": "sk-test", "MODEL": "provider-looking-model"},
            ("sk-test", "https://api.openai.com/v1", "provider-looking-model"),
        ),
    ]

    for env, expected in cases:
        settings = _resolve(monkeypatch, env)
        assert (settings.api_key, settings.base_url, settings.model) == expected
        assert settings.client_type == "openai"
        assert settings.api_version == ""


def test_resolve_rejects_invalid_numeric_permission_and_workspace(tmp_path, monkeypatch):
    fallback = _resolve(
        monkeypatch,
        {
            "FORGEAGENT_CTX_BUDGET": "many",
            "FORGEAGENT_MAX_ROUNDS": True,
            "FORGEAGENT_PERMISSION_MODE": ["danger"],
            "FORGEAGENT_WORKSPACE": ["~/project"],
        },
        cwd=tmp_path,
    )
    assert fallback.context_budget == 128000
    assert fallback.max_rounds == 60
    assert fallback.permission_mode == "prompt"
    assert fallback.workspace == str(tmp_path)

    non_positive = _resolve(
        monkeypatch,
        {"FORGEAGENT_CTX_BUDGET": "0", "FORGEAGENT_MAX_ROUNDS": "-1"},
    )
    assert non_positive.context_budget == 128000
    assert non_positive.max_rounds == 60

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert _resolve(monkeypatch, {"FORGEAGENT_WORKSPACE": "~/project"}).workspace == str(
        home / "project"
    )


def test_resolve_parses_hooks_prompt_cache_and_mcp(monkeypatch):
    settings = _resolve(
        monkeypatch,
        {
            "FORGEAGENT_HOOKS": " hooks/a.py : hooks/b.py,hooks/c.py ",
            "FORGEAGENT_PROMPT_CACHE": "yes",
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

    assert settings.hook_paths == ("hooks/a.py", "hooks/b.py", "hooks/c.py")
    assert settings.prompt_cache is True
    assert len(settings.mcp_servers) == 1
    assert settings.mcp_servers[0].name == "filesystem"
    assert settings.mcp_servers[0].command == "uvx"
    assert settings.mcp_servers[0].args == ("mcp-server-filesystem", "/tmp")


def test_replace_and_for_model_reuse_existing_endpoint(monkeypatch, mock_settings):
    server = MCPServerConfig(name="fs", command="uvx")
    settings = mock_settings.replace(mcp_servers=(server,))

    changed = settings.replace(model="gpt-5")
    assert changed.model == "gpt-5"
    assert settings.model == "test-model"
    assert changed.api_key == settings.api_key
    assert changed.context_budget == settings.context_budget
    assert changed.mcp_servers == (server,)

    monkeypatch.setattr(
        "forgeagent.core.settings._load_env_cascade",
        lambda: {"OPENAI_API_KEY": "sk-other"},
    )
    model_settings = settings.for_model(" custom-model ")
    assert model_settings.model == "custom-model"
    assert model_settings.api_key == settings.api_key
    assert model_settings.base_url == settings.base_url

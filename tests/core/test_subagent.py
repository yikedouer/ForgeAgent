"""test_subagent.py — 子 Agent 类型系统测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgeagent.frontmatter import parse_frontmatter
from forgeagent.core.subagent import (
    get_sub_agent_config,
    get_available_agent_types,
    build_agent_descriptions,
    reset_agent_cache,
    READ_ONLY_TOOLS,
    EXPLORE_PROMPT,
    PLAN_PROMPT,
    GENERAL_PROMPT,
)
from forgeagent.core.agent_store import create_agent_run


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后重置缓存。"""
    reset_agent_cache()
    yield
    reset_agent_cache()


# ═══════════════════════════════════════════════════════════
# 8.1 parse_frontmatter
# ═══════════════════════════════════════════════════════════

class TestParseFrontmatter:
    def test_valid(self):
        text = "---\nname: test\ndescription: A test\n---\nBody text"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "test"
        assert meta["description"] == "A test"
        assert body == "Body text"

    def test_no_frontmatter(self):
        text = "Just plain text"
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == "Just plain text"

    def test_missing_closing(self):
        text = "---\nname: test\nNo closing marker"
        meta, body = parse_frontmatter(text)
        assert meta == {}

    def test_preserves_body_whitespace_after_separator_blank(self):
        text = "---\nname: custom\n---\n\n  prompt\n\n"
        meta, body = parse_frontmatter(text)

        assert meta == {"name": "custom"}
        assert body == "  prompt\n\n"


# ═══════════════════════════════════════════════════════════
# 8.2 内置 Agent 类型
# ═══════════════════════════════════════════════════════════

class TestBuiltinAgents:
    def test_explore(self):
        config = get_sub_agent_config("explore")
        assert config["system_prompt"] == EXPLORE_PROMPT
        assert config["tool_names"] == READ_ONLY_TOOLS

    def test_plan(self):
        config = get_sub_agent_config("plan")
        assert config["system_prompt"] == PLAN_PROMPT
        assert config["tool_names"] == READ_ONLY_TOOLS

    def test_general(self):
        config = get_sub_agent_config("general")
        assert config["system_prompt"] == GENERAL_PROMPT
        assert config["tool_names"] is None

    def test_unknown_fallback_to_general(self):
        config = get_sub_agent_config("nonexistent_type")
        assert config["system_prompt"] == GENERAL_PROMPT
        assert config["tool_names"] is None


# ═══════════════════════════════════════════════════════════
# 8.3 自定义 Agent 发现
# ═══════════════════════════════════════════════════════════

class TestCustomAgentDiscovery:
    def test_project_level_agent(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".forgeagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Code reviewer\n---\nReview code carefully."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("reviewer")
        assert "Review code" in config["system_prompt"]

    def test_env_agents_dir_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        agents_dir = home / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Code reviewer\n---\nReview code carefully."
        )
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGEAGENT_AGENTS_DIR", "~/agents")
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("reviewer")

        assert "Review code" in config["system_prompt"]

    def test_project_overrides_user(self, tmp_path, monkeypatch):
        # 用户级
        user_agents = Path.home() / ".forgeagent" / "agents"
        # 项目级
        proj_agents = tmp_path / ".forgeagent" / "agents"
        proj_agents.mkdir(parents=True)
        (proj_agents / "custom.md").write_text(
            "---\nname: custom\ndescription: Project version\n---\nProject prompt."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("custom")
        assert "Project prompt" in config["system_prompt"]

    def test_allowed_tools_parsing(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".forgeagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "limited.md").write_text(
            "---\nname: limited\ndescription: Limited\nallowed-tools: read_file, grep_search\n---\nPrompt."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("limited")
        assert config["tool_names"] == {"read_file", "grep_search"}

    def test_allowed_tools_ignores_blank_entries(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".forgeagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "limited.md").write_text(
            "---\nname: limited\ndescription: Limited\n"
            "allowed-tools: read_file, , grep_search,\n---\nPrompt."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("limited")
        assert config["tool_names"] == {"read_file", "grep_search"}

    def test_blank_allowed_tools_means_unrestricted(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".forgeagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "open.md").write_text(
            "---\nname: open\ndescription: Open\nallowed-tools:\n---\nPrompt."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        config = get_sub_agent_config("open")
        assert config["tool_names"] is None


# ═══════════════════════════════════════════════════════════
# 8.4 get_available_agent_types
# ═══════════════════════════════════════════════════════════

class TestGetAvailableAgentTypes:
    def test_includes_builtins(self):
        types = get_available_agent_types()
        names = {t["name"] for t in types}
        assert {"explore", "plan", "general"}.issubset(names)

    def test_each_has_description(self):
        for t in get_available_agent_types():
            assert "name" in t
            assert "description" in t


# ═══════════════════════════════════════════════════════════
# 8.5 build_agent_descriptions
# ═══════════════════════════════════════════════════════════

class TestBuildAgentDescriptions:
    def test_no_custom_returns_empty(self):
        assert build_agent_descriptions() == ""

    def test_with_custom(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".forgeagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "tester.md").write_text(
            "---\nname: tester\ndescription: Test runner\n---\nRun tests."
        )
        monkeypatch.chdir(tmp_path)
        reset_agent_cache()

        desc = build_agent_descriptions()
        assert "tester" in desc
        assert "Test runner" in desc


class TestAgentStore:
    def test_agent_store_override_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGEAGENT_AGENT_STORE", "~/agent-runs")

        md_path, json_path = create_agent_run(
            str(tmp_path), "agent1", "agent", "test agent", "general", "m", "prompt"
        )

        assert md_path == home / "agent-runs" / "agent1.md"
        assert json_path == home / "agent-runs" / "agent1.json"
        assert md_path.exists()

    def test_create_agent_run_rejects_agent_id_path_traversal(self, tmp_path):
        outside = tmp_path / ".forgeagent" / "escape.md"

        with pytest.raises(ValueError, match="Invalid agent_id"):
            create_agent_run(
                str(tmp_path),
                "../escape",
                "bad",
                "bad agent",
                "general",
                "m",
                "prompt",
            )

        assert not outside.exists()

    def test_create_agent_run_rejects_whitespace_only_agent_id(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid agent_id"):
            create_agent_run(
                str(tmp_path),
                "   ",
                "bad",
                "bad agent",
                "general",
                "m",
                "prompt",
            )

    def test_create_agent_run_rejects_non_string_agent_id(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid agent_id"):
            create_agent_run(
                str(tmp_path),
                123,
                "bad",
                "bad agent",
                "general",
                "m",
                "prompt",
            )

    def test_create_agent_run_caps_long_agent_ids_without_collision(self, tmp_path):
        first_id = "agent_" + "x" * 300 + "a"
        second_id = "agent_" + "x" * 300 + "b"

        first_md, first_json = create_agent_run(
            str(tmp_path), first_id, "first", "first agent", "general", "m", "prompt"
        )
        second_md, second_json = create_agent_run(
            str(tmp_path), second_id, "second", "second agent", "general", "m", "prompt"
        )

        assert first_md != second_md
        assert first_json != second_json
        assert first_md.exists()
        assert second_md.exists()
        assert len(first_md.name.encode("utf-8")) <= 255
        assert len(second_md.name.encode("utf-8")) <= 255

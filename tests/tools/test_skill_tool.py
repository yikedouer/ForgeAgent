"""test_skill_tool.py — skill 工具桥接测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecc.tools.skill import skill
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
    body: str = "Handle $ARGUMENTS",
) -> None:
    skill_dir = root / ".forgecc" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n{frontmatter}---\n{body}",
        encoding="utf-8",
    )


class TestSkillTool:
    def test_empty_skill_name_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = skill("")

        assert "INVALID SKILL" in result

    def test_non_string_skill_name_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = skill(123)

        assert "INVALID SKILL" in result

    def test_skill_name_trims_whitespace(self, tmp_path, monkeypatch):
        _write_skill(tmp_path, "helper", "", "Help $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = skill(" helper ", "now")

        assert '[Skill "helper" activated]' in result
        assert "Help now" in result

    def test_non_string_args_rejected(self, tmp_path, monkeypatch):
        _write_skill(tmp_path, "helper", "", "Help $ARGUMENTS")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = skill("helper", 123)

        assert "INVALID ARGS" in result

    def test_fork_skill_uses_sub_agent_entrypoint(self, tmp_path, monkeypatch):
        _write_skill(
            tmp_path,
            "forker",
            "context: fork\nallowed-tools: read_file, grep_search\n",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        calls = []

        def fake_execute_sub_agent(
            agent_type, description, prompt, model=None, allowed_tools=None,
        ):
            calls.append((agent_type, description, prompt, model, allowed_tools))
            return "forked result"

        monkeypatch.setattr(
            "forgecc.core.engine.Engine.execute_sub_agent",
            staticmethod(fake_execute_sub_agent),
        )

        result = skill("forker", "the task")

        assert result == "forked result"
        assert calls
        agent_type, description, prompt, model, allowed_tools = calls[0]
        assert agent_type == "general"
        assert "forker" in description
        assert "Handle the task" in prompt
        assert "read_file, grep_search" in prompt
        assert model is None
        assert allowed_tools == ("read_file", "grep_search")

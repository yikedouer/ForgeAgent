"""技能系统测试 — forgecc.skills (frontmatter + playbook)"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forgecc.skills.frontmatter import parse_frontmatter, Frontmatter
from forgecc.skills import playbook as pb_mod
from forgecc.skills.playbook import (
    Playbook,
    discover,
    invalidate_cache,
    find,
    resolve_template,
    invoke,
    describe_for_directive,
    _load_one,
)


# ═══════════════════════════════════════════════════════════════
# Fixture: 每个测试清除 playbook 缓存
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_playbook_cache():
    invalidate_cache()
    yield
    invalidate_cache()


# ═══════════════════════════════════════════════════════════════
# 1. skills/frontmatter.py
# ═══════════════════════════════════════════════════════════════

class TestSkillFrontmatter:
    def test_valid(self):
        raw = "---\nname: test\ndescription: A test skill\n---\nBody"
        result = parse_frontmatter(raw)
        assert isinstance(result, Frontmatter)
        assert result.meta == {"name": "test", "description": "A test skill"}
        assert result.body == "Body"

    def test_no_frontmatter(self):
        raw = "Just plain text."
        result = parse_frontmatter(raw)
        assert result.meta == {}
        assert result.body == raw

    def test_missing_closing(self):
        raw = "---\nname: test\nNo closing"
        result = parse_frontmatter(raw)
        assert result.meta == {}
        assert result.body == raw

    def test_preserves_body_whitespace_after_separator_blank(self):
        raw = "---\nname: test\n---\n\n  indented\n\n"
        result = parse_frontmatter(raw)

        assert result.meta == {"name": "test"}
        assert result.body == "  indented\n\n"

    def test_frozen(self):
        result = parse_frontmatter("---\nname: x\n---\nbody")
        with pytest.raises(AttributeError):
            result.meta = {}


# ═══════════════════════════════════════════════════════════════
# 2. _load_one
# ═══════════════════════════════════════════════════════════════

class TestLoadOne:
    def _make_skill(self, tmp_path, name: str, extra_meta: str = "") -> Path:
        skill_dir = tmp_path / name
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            f"---\nname: {name}\ndescription: {name} skill\n{extra_meta}---\nTemplate body $ARGUMENTS",
            encoding="utf-8",
        )
        return skill_file

    def test_basic_load(self, tmp_path):
        path = self._make_skill(tmp_path, "myskill")
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.name == "myskill"
        assert pb.mode == "inline"
        assert pb.user_invocable is True
        assert pb.allowed_tools is None

    def test_fork_mode(self, tmp_path):
        path = self._make_skill(tmp_path, "fork_skill", "context: fork\n")
        pb = _load_one(path, "user", str(path.parent))
        assert pb is not None
        assert pb.mode == "fork"

    def test_allowed_tools_csv(self, tmp_path):
        path = self._make_skill(tmp_path, "limited", "allowed-tools: read_file, grep_search\n")
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.allowed_tools == ("read_file", "grep_search")

    def test_allowed_tools_json(self, tmp_path):
        path = self._make_skill(tmp_path, "json_tools", 'allowed-tools: ["shell", "write_file"]\n')
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.allowed_tools == ("shell", "write_file")

    def test_allowed_tools_json_filters_non_strings(self, tmp_path):
        path = self._make_skill(
            tmp_path,
            "mixed_tools",
            'allowed-tools: ["read_file", 123, null, "grep_search"]\n',
        )
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.allowed_tools == ("read_file", "grep_search")

    def test_allowed_tools_json_like_trailing_comma_strips_quotes(self, tmp_path):
        path = self._make_skill(
            tmp_path,
            "json_like_tools",
            'allowed-tools: ["read_file", "grep_search",]\n',
        )
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.allowed_tools == ("read_file", "grep_search")

    def test_user_invocable_false(self, tmp_path):
        path = self._make_skill(tmp_path, "auto", "user-invocable: false\n")
        pb = _load_one(path, "project", str(path.parent))
        assert pb is not None
        assert pb.user_invocable is False


# ═══════════════════════════════════════════════════════════════
# 3. discover / find / invalidate_cache
# ═══════════════════════════════════════════════════════════════

class TestDiscoverAndFind:
    def test_discover_scans(self, tmp_path, monkeypatch):
        # 设置项目级技能目录
        skills_dir = tmp_path / ".forgecc" / "skills" / "test_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: test_skill\ndescription: A skill\n---\nBody",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        # 避免扫描用户目录
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        playbooks = discover()
        assert any(p.name == "test_skill" for p in playbooks)

    def test_find_found(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / ".forgecc" / "skills" / "findme"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: findme\ndescription: Found\n---\nBody",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = find("findme")
        assert result is not None
        assert result.name == "findme"

    def test_find_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
        assert find("nonexistent") is None

    def test_cache_invalidation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        first = discover()
        # 缓存后再次调用返回同一引用
        second = discover()
        assert first is second

        invalidate_cache()
        third = discover()
        assert third is not first


# ═══════════════════════════════════════════════════════════════
# 4. resolve_template / invoke
# ═══════════════════════════════════════════════════════════════

class TestResolveAndInvoke:
    def test_resolve_template(self):
        pb = Playbook(
            name="test", description="", hint="", mode="inline",
            user_invocable=True, allowed_tools=None,
            template="Do $ARGUMENTS in ${SKILL_DIR}",
            origin="project", directory="/skills/test",
        )
        result = resolve_template(pb, "my task")
        assert result == "Do my task in /skills/test"

    def test_invoke_found(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / ".forgecc" / "skills" / "greet"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: greet\ndescription: Greet\n---\nHello $ARGUMENTS",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = invoke("greet", "world")
        assert result is not None
        assert result["prompt"] == "Hello world"
        assert result["mode"] == "inline"

    def test_invoke_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
        assert invoke("nothing") is None


# ═══════════════════════════════════════════════════════════════
# 5. describe_for_directive
# ═══════════════════════════════════════════════════════════════

class TestDescribeForDirective:
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
        assert describe_for_directive() == ""

    def test_with_skills(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / ".forgecc" / "skills" / "demo"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill\nwhen-to-use: When needed\n---\nBody",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        result = describe_for_directive()
        assert "Registered Skills" in result
        assert "/demo" in result
        assert "Demo skill" in result

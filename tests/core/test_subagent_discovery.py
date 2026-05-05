"""Custom sub-agent discovery tests."""

from __future__ import annotations

from forgeagent.frontmatter import parse_frontmatter
from forgeagent.core.subagent import _parse_allowed_tools, discover_custom_agents


def test_parse_frontmatter_returns_metadata_and_body() -> None:
    meta, body = parse_frontmatter("---\nname: test\ndescription: A test\n---\nBody")

    assert meta == {"name": "test", "description": "A test"}
    assert body == "Body"


def test_parse_allowed_tools_returns_none_for_blank_entries() -> None:
    assert _parse_allowed_tools(" , ") is None


def test_discover_custom_agents_project_overrides_user(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    user_agents = home / ".forgeagent" / "agents"
    project_agents = tmp_path / ".forgeagent" / "agents"
    user_agents.mkdir(parents=True)
    project_agents.mkdir(parents=True)
    (user_agents / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: User\n---\nUser prompt",
        encoding="utf-8",
    )
    (project_agents / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Project\n"
        "allowed-tools: read_file, grep_search\n---\nProject prompt",
        encoding="utf-8",
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.chdir(tmp_path)

    agents = discover_custom_agents()

    assert agents["reviewer"]["description"] == "Project"
    assert agents["reviewer"]["system_prompt"] == "Project prompt"
    assert agents["reviewer"]["allowed_tools"] == {"read_file", "grep_search"}

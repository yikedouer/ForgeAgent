"""Custom sub-agent definition discovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse simple ``key: value`` frontmatter from an agent definition."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    header = text[3:end].strip()
    body = text[end + 3:]
    if body.startswith("\n"):
        body = body[1:]
    if body.startswith("\n"):
        body = body[1:]

    meta: dict[str, str] = {}
    for line in header.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()

    return meta, body


def _parse_allowed_tools(raw: str) -> set[str] | None:
    names = {name.strip() for name in raw.split(",") if name.strip()}
    return names or None


def _load_agents_from_dir(
    directory: Path,
    agents: dict[str, dict[str, Any]],
) -> None:
    """Load ``*.md`` agent definition files from a directory."""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if entry.suffix != ".md":
            continue
        try:
            raw = entry.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name") or entry.stem
            allowed_tools: set[str] | None = None
            if "allowed-tools" in meta:
                allowed_tools = _parse_allowed_tools(meta["allowed-tools"])
            agents[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "allowed_tools": allowed_tools,
                "system_prompt": body,
            }
        except Exception:
            pass


def discover_custom_agents() -> dict[str, dict[str, Any]]:
    """Load custom agents from user, env override, and project directories."""
    agents: dict[str, dict[str, Any]] = {}
    home = Path.home()
    cwd = Path.cwd()

    _load_agents_from_dir(home / ".claude" / "agents", agents)
    _load_agents_from_dir(home / ".forgecc" / "agents", agents)
    env_dir = os.environ.get("FORGECC_AGENTS_DIR")
    if env_dir:
        _load_agents_from_dir(Path(env_dir).expanduser(), agents)

    _load_agents_from_dir(cwd / ".claude" / "agents", agents)
    _load_agents_from_dir(cwd / ".forgecc" / "agents", agents)

    return agents

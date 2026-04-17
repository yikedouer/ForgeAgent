"""Playbook — skill discovery, parsing, and execution.

A "playbook" is a reusable prompt template stored as a Markdown file
with YAML-style frontmatter. Playbooks live in well-known directories
and are surfaced to the LLM as callable skills.

Directory layout:
    .forgecc/skills/<name>/SKILL.md   (project-level, higher priority)
    ~/.forgecc/skills/<name>/SKILL.md  (user-level, lower priority)
    .claude/skills/<name>/SKILL.md     (compatibility with Claude Code)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontmatter import parse_frontmatter


# ── Playbook definition ─────────────────────────────────────

@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    hint: str               # when-to-use guidance for the LLM
    mode: str               # "inline" or "fork"
    user_invocable: bool
    allowed_tools: tuple[str, ...] | None
    template: str           # raw prompt body with $ARGUMENTS placeholders
    origin: str             # "project" | "user" | "compat"
    directory: str          # absolute path to skill directory


# ── Discovery ───────────────────────────────────────────────
# Scans multiple directories in priority order.  Later entries
# overwrite earlier ones for the same name.

_cache: list[Playbook] | None = None


def _scan_dir(base: Path, origin: str, out: dict[str, Playbook]) -> None:
    if not base.is_dir():
        return
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        pb = _load_one(skill_file, origin, str(child))
        if pb is not None:
            out[pb.name] = pb


def _load_one(path: Path, origin: str, directory: str) -> Playbook | None:
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    meta = fm.meta
    name = meta.get("name") or path.parent.name

    # parse allowed-tools
    allowed: tuple[str, ...] | None = None
    raw_tools = meta.get("allowed-tools", "")
    if raw_tools:
        if raw_tools.startswith("["):
            try:
                allowed = tuple(json.loads(raw_tools))
            except Exception:
                allowed = tuple(s.strip() for s in raw_tools.strip("[]").split(",") if s.strip())
        else:
            allowed = tuple(s.strip() for s in raw_tools.split(",") if s.strip())

    return Playbook(
        name=name,
        description=meta.get("description", ""),
        hint=meta.get("when-to-use", "") or meta.get("when_to_use", ""),
        mode="fork" if meta.get("context") == "fork" else "inline",
        user_invocable=meta.get("user-invocable", "true").lower() != "false",
        allowed_tools=allowed if allowed else None,
        template=fm.body,
        origin=origin,
        directory=directory,
    )


def discover() -> list[Playbook]:
    """Return all discovered playbooks, cached after first call."""
    global _cache
    if _cache is not None:
        return _cache

    collected: dict[str, Playbook] = {}

    # user-level (lowest priority)
    _scan_dir(Path.home() / ".forgecc" / "skills", "user", collected)

    # compatibility: .claude/skills
    _scan_dir(Path.cwd() / ".claude" / "skills", "compat", collected)

    # project-level (highest priority)
    _scan_dir(Path.cwd() / ".forgecc" / "skills", "project", collected)

    _cache = list(collected.values())
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None


# ── Resolution ──────────────────────────────────────────────

def find(name: str) -> Playbook | None:
    for pb in discover():
        if pb.name == name:
            return pb
    return None


def resolve_template(pb: Playbook, arguments: str) -> str:
    """Substitute $ARGUMENTS / ${ARGUMENTS} and ${SKILL_DIR}."""
    text = pb.template
    text = re.sub(r"\$ARGUMENTS|\$\{ARGUMENTS\}", arguments, text)
    text = text.replace("${SKILL_DIR}", pb.directory)
    return text


def invoke(name: str, arguments: str = "") -> dict[str, Any] | None:
    """Prepare a playbook for execution. Returns None if not found."""
    pb = find(name)
    if pb is None:
        return None
    return {
        "prompt": resolve_template(pb, arguments),
        "mode": pb.mode,
        "allowed_tools": pb.allowed_tools,
    }


# ── System prompt fragment ──────────────────────────────────

def describe_for_directive() -> str:
    """Build a text section describing available skills for the system prompt."""
    playbooks = discover()
    if not playbooks:
        return ""

    parts = ["# Registered Skills", ""]
    manual = [p for p in playbooks if p.user_invocable]
    auto = [p for p in playbooks if not p.user_invocable]

    if manual:
        parts.append("Skills the user can invoke with /<name>:")
        for p in manual:
            parts.append(f"  - /{p.name}: {p.description}")
            if p.hint:
                parts.append(f"    Hint: {p.hint}")
        parts.append("")

    if auto:
        parts.append("Skills for automatic use (call via the skill instrument):")
        for p in auto:
            parts.append(f"  - {p.name}: {p.description}")
            if p.hint:
                parts.append(f"    Hint: {p.hint}")
        parts.append("")

    return "\n".join(parts)

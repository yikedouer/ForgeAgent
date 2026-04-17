"""Dynamic system-prompt assembly.

The system directive is rebuilt before every LLM call so it always
reflects the current environment. It weaves together:

  1. Role framing — what the agent is and how it should behave.
  2. Environment snapshot — OS, cwd, timestamp, git branch.
  3. Instrument manifest — concise list of available tools.
  4. Project rules — content of FORGECC.md / CLAUDE.md if present.
"""

from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime

from ..core.settings import Settings
from .. import toolkit
from ..skills import playbook


def _git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _project_rules(workspace: str) -> str:
    """Load project-level guidance from well-known files."""
    candidates = ["FORGECC.md", "CLAUDE.md", ".forgecc/rules.md"]
    for name in candidates:
        path = os.path.join(workspace, name)
        if os.path.isfile(path):
            try:
                content = open(path, "r", encoding="utf-8").read(8_000)
                return f"\n<project_rules source=\"{name}\">\n{content}\n</project_rules>\n"
            except Exception:
                continue
    return ""


def _instrument_manifest() -> str:
    """One-line-per-instrument summary for the system prompt."""
    lines = []
    for spec in toolkit.catalog().values():
        lines.append(f"  - {spec.name}: {spec.description}")
    return "\n".join(lines)


def build(settings: Settings) -> str:
    """Assemble the complete system directive."""

    branch = _git_branch()
    rules = _project_rules(settings.workspace)
    instruments = _instrument_manifest()

    parts = [
        "You are ForgeCC, an autonomous coding agent. You solve programming "
        "tasks by reading files, searching code, editing files, and running "
        "shell commands. Work iteratively: make a change, verify it, then "
        "continue until the task is fully complete.",
        "",
        "# Environment",
        f"  OS: {platform.system()} {platform.release()}",
        f"  CWD: {settings.workspace}",
        f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]

    if branch:
        parts.append(f"  Git branch: {branch}")

    parts += [
        "",
        "# Available instruments",
        instruments,
        "",
        "# Operating rules",
        "- Always verify changes by reading back the file or running tests.",
        "- Use edit_file for surgical changes; write_file only for new files.",
        "- When a shell command fails, read the error and fix the root cause.",
        "- If the task is ambiguous, state your assumptions before acting.",
        "- Keep responses concise — let tool results speak.",
    ]

    if rules:
        parts.append(rules)

    skill_section = playbook.describe_for_directive()
    if skill_section:
        parts.append("")
        parts.append(skill_section)

    return "\n".join(parts)

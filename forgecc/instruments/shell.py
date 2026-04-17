"""Shell command execution with safety guardrails.

Safety model (two-phase):
  Phase 1 — static pattern scan rejects catastrophic commands before
            they ever reach the OS.
  Phase 2 — output is captured with a hard timeout so a runaway
            process can't block the agent loop.
"""

from __future__ import annotations

import os
import re
import subprocess

from ..toolkit import instrument

# ── Phase-1 rejection patterns ──────────────────────────────
# Each tuple: (compiled regex, human-readable reason)

_REJECTION_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+.*-r.*\s+[/~]"), "recursive removal at root or home"),
    (re.compile(r"\bmkfs\b"), "filesystem formatting"),
    (re.compile(r"\bdd\b.*\bof=/dev/"), "raw device write"),
    (re.compile(r">\s*/dev/sd"), "block-device overwrite"),
    (re.compile(r":\(\)\{.*\|.*\}"), "fork bomb pattern"),
    (re.compile(r"\bcurl\b.*\|\s*(?:sudo\s+)?(?:ba)?sh"), "piping remote script to shell"),
    (re.compile(r"\bwget\b.*\|\s*(?:sudo\s+)?(?:ba)?sh"), "piping remote script to shell"),
    (re.compile(r"\bchmod\b.*777\s+/"), "world-writable root"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b"), "system power command"),
    (re.compile(r"\bnc\b.*-[le]"), "netcat listener"),
]

# working directory persists across calls (mirrors real terminal)
_wd: str | None = None


def _check_safety(cmd: str) -> str | None:
    """Return rejection reason or None if safe."""
    for pattern, reason in _REJECTION_RULES:
        if pattern.search(cmd):
            return reason
    return None


def _track_directory(cmd: str, current: str) -> str:
    """Update working directory if the command contains a cd."""
    # naive but effective: detect leading `cd <path>` or `cd <path> &&`
    m = re.match(r"^cd\s+(\S+)", cmd.strip())
    if m:
        target = m.group(1)
        resolved = os.path.normpath(os.path.join(current, target))
        if os.path.isdir(resolved):
            return resolved
    return current


@instrument(
    name="shell",
    description=(
        "Run a shell command and return its combined stdout/stderr. "
        "The working directory persists between calls. "
        "Use for builds, tests, git, package managers, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to execute"},
            "timeout": {"type": "integer", "description": "Seconds before kill (default 120)"},
        },
        "required": ["command"],
    },
    risk_level="danger",
)
def shell(command: str, timeout: int = 120) -> str:
    global _wd

    # Phase 1: static safety scan
    reason = _check_safety(command)
    if reason:
        return f"BLOCKED — {reason}: {command}"

    if _wd is None:
        _wd = os.getcwd()

    _wd = _track_directory(command, _wd)

    # Phase 2: execute with timeout and output capture
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_wd,
        )
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s: {command}"

    parts = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(proc.stderr)
    output = "\n".join(parts).strip()

    # truncate massive output — keep head + tail
    MAX_CHARS = 40_000
    if len(output) > MAX_CHARS:
        half = MAX_CHARS // 2
        output = (
            output[:half]
            + f"\n\n... ({len(output) - MAX_CHARS} chars omitted) ...\n\n"
            + output[-half:]
        )

    status = f"[exit {proc.returncode}]"
    return f"{status}\n{output}" if output else status

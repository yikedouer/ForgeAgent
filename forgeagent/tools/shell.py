"""带安全护栏的 Shell 命令执行。

安全模型（两阶段）：
  第 1 阶段 — 静态模式扫描，在命令到达操作系统前拒绝
            灾难性命令。
  第 2 阶段 — 输出捕获带硬超时，防止失控进程
            阻塞 Agent 循环。
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess

from ..toolkit import tool
from .paths import active_workspace

log = logging.getLogger(__name__)
_PWD_MARKER = "__FORGEAGENT_PWD__"

# ── 第 1 阶段拒绝模式 ──────────────────────────────────────
# 每个元组：(编译后的正则, 可读的拒绝原因)

_REJECTION_RULES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\brm\s+.*-[A-Za-z]*[rR][A-Za-z]*.*\s+['\"]?(?:[/~]|\$HOME|\$\{HOME\})"),
        "recursive removal at root or home",
    ),
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

# 工作目录在调用间持久化（模拟真实终端）
_wd: str | None = None


def _initial_working_directory() -> str:
    """Return the active workspace when available, otherwise the process cwd."""
    try:
        from ..core.engine import _active_engine

        if _active_engine is not None:
            workspace = _active_engine.settings.workspace
            if os.path.isdir(workspace):
                return workspace
    except Exception:
        pass
    return os.getcwd()


def _check_safety(cmd: str) -> str | None:
    """返回拒绝原因，安全则返回 None。"""
    for pattern, reason in _REJECTION_RULES:
        if pattern.search(cmd):
            return reason
    return None


def _expand_shell_vars(text: str) -> str:
    """Expand simple shell variables, treating undefined names as empty."""
    text = os.path.expanduser(text)
    return re.sub(
        r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
        lambda match: os.environ.get(match.group(1) or match.group(2), ""),
        text,
    )


def _resolve_cd_target(target: str, current: str) -> str:
    resolved = _expand_shell_vars(target)
    if resolved == "":
        resolved = os.path.expanduser("~")
    if not os.path.isabs(resolved):
        resolved = os.path.join(current, resolved)
    return os.path.normpath(resolved)


def _track_directory(cmd: str, current: str) -> str:
    """如果命令包含 cd，更新工作目录。"""
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return current

    cwd = current
    command: list[str] = []
    should_run = True
    last_status: bool | None = True

    def apply_command(parts: list[str], run: bool, prior: bool | None) -> bool | None:
        nonlocal cwd
        if not parts:
            return prior
        if not run:
            return prior
        if parts[0] == "true":
            return True
        if parts[0] == "false":
            return False
        if parts[0] != "cd":
            return None
        target = parts[1] if len(parts) >= 2 else "~"
        resolved = _resolve_cd_target(target, cwd)
        if os.path.isdir(resolved):
            cwd = resolved
            return True
        return False

    for token in tokens + [";"]:
        if token in {"&&", "||", ";"}:
            last_status = apply_command(command, should_run, last_status)
            command = []
            if token == "&&":
                should_run = last_status in (True, None)
            elif token == "||":
                should_run = last_status is False
            else:
                should_run = True
            continue
        command.append(token)
    return cwd


def _possible_cd_targets(cmd: str, current: str) -> list[str]:
    """Return syntactic cd targets that may run, without requiring existence."""
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []

    cwd = current
    command: list[str] = []
    targets: list[str] = []
    should_run = True
    last_status: bool | None = True

    def apply_command(parts: list[str], run: bool, prior: bool | None) -> bool | None:
        nonlocal cwd
        if not parts:
            return prior
        if not run:
            return prior
        if parts[0] == "true":
            return True
        if parts[0] == "false":
            return False
        if parts[0] != "cd":
            return None
        target = parts[1] if len(parts) >= 2 else "~"
        resolved = _resolve_cd_target(target, cwd)
        targets.append(resolved)
        cwd = resolved
        return True

    for token in tokens + [";"]:
        if token in {"&&", "||", ";"}:
            last_status = apply_command(command, should_run, last_status)
            command = []
            if token == "&&":
                should_run = last_status in (True, None)
            elif token == "||":
                should_run = last_status in (False, None)
            else:
                should_run = True
            continue
        command.append(token)
    return targets


def _command_with_pwd_marker(command: str) -> str:
    return (
        f"{command}\n"
        "__forgeagent_status=$?\n"
        f"printf '\\n{_PWD_MARKER}%s\\n' \"$PWD\"\n"
        "exit $__forgeagent_status"
    )


def _workspace_scoped_cwd(current: str) -> str:
    """Keep persisted shell cwd inside the currently active workspace."""
    workspace = active_workspace()
    if workspace is None:
        return current
    if os.path.isdir(current):
        from ..core.permissions import check_workspace_boundary

        if check_workspace_boundary(current, workspace) is None:
            return current
    if os.path.isdir(workspace):
        return os.path.normpath(workspace)
    return current


def _extract_pwd_marker(output: str) -> tuple[str, str | None]:
    marker_at = output.rfind(_PWD_MARKER)
    if marker_at < 0:
        return output, None
    content = output[:marker_at]
    tail = output[marker_at + len(_PWD_MARKER):]
    pwd, _, rest = tail.partition("\n")
    if rest.strip():
        return output, None
    if content.endswith("\n"):
        content = content[:-1]
    return content, pwd or None


@tool(
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

    if not isinstance(command, str) or not command.strip():
        return "INVALID COMMAND: command must be non-empty."

    # 第 1 阶段：静态安全扫描
    reason = _check_safety(command)
    if reason:
        log.warning("shell 被拦截: %s — %s", reason, command[:120])
        return f"BLOCKED — {reason}: {command}"
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        return "INVALID TIMEOUT: timeout must be positive."

    if _wd is None or not os.path.isdir(_wd):
        _wd = _initial_working_directory()
    _wd = _workspace_scoped_cwd(_wd)

    run_cwd = _wd
    workspace = active_workspace()
    if workspace is not None:
        from ..core.permissions import check_workspace_boundary

        for target in _possible_cd_targets(command, run_cwd):
            boundary_err = check_workspace_boundary(target, workspace)
            if boundary_err:
                return boundary_err

    log.debug("shell 执行: cwd=%s  cmd=%s  timeout=%ds", run_cwd, command[:200], timeout)

    # 第 2 阶段：带超时和输出捕获的执行
    try:
        proc = subprocess.run(
            _command_with_pwd_marker(command),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
        )
    except subprocess.TimeoutExpired:
        log.warning("shell 超时: %ds  cmd=%s", timeout, command[:120])
        return f"TIMEOUT after {timeout}s: {command}"

    stdout, final_cwd = _extract_pwd_marker(proc.stdout or "")
    if final_cwd and os.path.isdir(final_cwd):
        _wd = os.path.normpath(final_cwd)
    else:
        _wd = run_cwd

    parts = []
    if stdout:
        parts.append(stdout)
    if proc.stderr:
        parts.append(proc.stderr)
    output = "\n".join(parts).strip()

    # 截断超大输出——保留头尾
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

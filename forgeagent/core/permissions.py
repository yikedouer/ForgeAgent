"""权限系统 — 将危险操作拦截在确认之后。

权限模式（从最严到最宽松）：
  PLAN      — 只读规划；write/danger 被阻止（plan 文件由 Engine 例外处理）
  READONLY  — 仅允许 read 级工具
  PROMPT    — write 允许，danger 需交互确认（默认）
  WRITE     — read + write 允许，danger 被阻止
  DANGER    — 全部允许，无确认

每个工具声明一个 risk_level（'read' / 'write' / 'danger'）。
PermissionEnforcer 在执行前检查（模式 × 风险级别）。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path


# ── 权限模式 ────────────────────────────────────────────

class PermissionMode(Enum):
    PLAN = "plan"          # 只读规划；写操作由 Engine 流程控制
    READONLY = "readonly"
    WRITE = "write"
    PROMPT = "prompt"      # 默认 — danger 操作需交互确认
    DANGER = "danger"      # 全部允许，无确认


# ── 工具风险级别 ──────────────────────────────────────────

RISK_READ = "read"
RISK_WRITE = "write"
RISK_DANGER = "danger"

_RISK_ORDER = {RISK_READ: 0, RISK_WRITE: 1, RISK_DANGER: 2}
_PATH_ARG_NAMES = ("path", "file", "filepath", "file_path", "root")


# ── 工作区边界检查 ─────────────────────────────────────

def check_workspace_boundary(filepath: str, workspace: str) -> str | None:
    """如果 `filepath` 在工作区外则返回错误信息，否则返回 None。"""
    try:
        ws = Path(workspace).resolve()
        candidate = Path(filepath).expanduser()
        if not candidate.is_absolute():
            candidate = ws / candidate
        resolved = candidate.resolve()
        # 如果解析后的路径以工作区开头则允许
        if resolved == ws or str(resolved).startswith(str(ws) + os.sep):
            return None
        return (
            f"DENIED — path '{resolved}' is outside workspace '{ws}'. "
            "File operations are restricted to the project directory."
        )
    except Exception as exc:
        return f"DENIED — path validation error: {exc}"


# ── 权限执行器 ─────────────────────────────────────────

class PermissionEnforcer:
    """无状态检查器，按风险级别拦截工具执行。"""

    def __init__(self, mode: PermissionMode, workspace: str):
        self.mode = mode
        self.workspace = workspace
        self._prompter: callable | None = None

    def set_prompter(self, fn: callable) -> None:
        """注册交互确认回调。

        fn(tool_name, args) -> bool  (True = 允许，False = 拒绝)
        """
        self._prompter = fn

    def check(self, tool_name: str, risk_level: str, args: object) -> str | None:
        """允许时返回 None，否则返回拒绝原因字符串。

        同时对文件操作工具执行工作区边界检查。
        """
        if not isinstance(args, dict):
            return (
                f"DENIED — invalid arguments for '{tool_name}': "
                "arguments must be an object"
            )

        # 1. 基于模式的访问控制
        denial = self._check_mode(tool_name, risk_level, args)
        if denial:
            return denial

        # 2. 文件工具的工作区边界检查
        if risk_level in (RISK_WRITE, RISK_READ):
            path_args = (args[name] for name in _PATH_ARG_NAMES if args.get(name))
            for path_arg in path_args:
                boundary_err = check_workspace_boundary(path_arg, self.workspace)
                if boundary_err:
                    return boundary_err

        return None

    def _check_mode(
        self,
        tool_name: str,
        risk_level: str,
        args: dict | None = None,
    ) -> str | None:
        risk = _RISK_ORDER.get(risk_level) if isinstance(risk_level, str) else None
        if risk is None:
            return f"DENIED — unknown risk level '{risk_level}' for '{tool_name}'"

        if self.mode == PermissionMode.DANGER:
            return None  # 全部允许

        if self.mode == PermissionMode.PLAN:
            if risk > _RISK_ORDER[RISK_READ]:
                return (
                    f"[plan mode] {tool_name} blocked — "
                    "only read tools and plan file editing allowed"
                )
            return None

        if self.mode == PermissionMode.READONLY:
            if risk > _RISK_ORDER[RISK_READ]:
                return f"DENIED — mode is READONLY, cannot run '{tool_name}' (risk: {risk_level})"
            return None

        if self.mode == PermissionMode.WRITE:
            if risk > _RISK_ORDER[RISK_WRITE]:
                return f"DENIED — mode is WRITE, cannot run '{tool_name}' (risk: danger)"
            return None

        # PROMPT 模式（默认）
        if risk <= _RISK_ORDER[RISK_WRITE]:
            return None  # read + write 自动允许

        # danger 级别 → 询问用户
        if self._prompter:
            try:
                allowed = self._prompter(tool_name, args or {})
            except Exception as exc:
                return f"DENIED — confirmation failed for '{tool_name}': {exc}"
            if allowed:
                return None
            return f"DENIED — user rejected '{tool_name}'"

        # 未注册 prompter → 默认拒绝
        return f"DENIED — '{tool_name}' requires confirmation but no interactive session"

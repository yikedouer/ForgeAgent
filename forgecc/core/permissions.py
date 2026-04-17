"""Permission system — gating dangerous operations behind confirmation.

Permission modes (from least to most permissive):
  READONLY  — only read-level tools allowed
  PROMPT    — write allowed, danger requires interactive confirmation (default)
  WRITE     — read + write allowed, danger blocked
  DANGER    — everything allowed, no confirmation

Each instrument declares a risk_level ('read' / 'write' / 'danger').
The PermissionEnforcer checks (mode × risk_level) before execution.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path


# ── Permission mode ────────────────────────────────────────

class PermissionMode(Enum):
    READONLY = "readonly"
    WRITE = "write"
    PROMPT = "prompt"      # default — interactive confirmation for danger
    DANGER = "danger"      # full access, no confirmation


# ── Risk levels for instruments ────────────────────────────

RISK_READ = "read"
RISK_WRITE = "write"
RISK_DANGER = "danger"

_RISK_ORDER = {RISK_READ: 0, RISK_WRITE: 1, RISK_DANGER: 2}


# ── Workspace boundary validation ─────────────────────────

def check_workspace_boundary(filepath: str, workspace: str) -> str | None:
    """Return an error message if `filepath` is outside workspace, else None."""
    try:
        resolved = Path(filepath).expanduser().resolve()
        ws = Path(workspace).resolve()
        # allow if resolved path starts with workspace
        if resolved == ws or str(resolved).startswith(str(ws) + os.sep):
            return None
        return (
            f"DENIED — path '{resolved}' is outside workspace '{ws}'. "
            "File operations are restricted to the project directory."
        )
    except Exception as exc:
        return f"DENIED — path validation error: {exc}"


# ── Permission enforcer ───────────────────────────────────

class PermissionEnforcer:
    """Stateless checker that gates instrument execution by risk level."""

    def __init__(self, mode: PermissionMode, workspace: str):
        self.mode = mode
        self.workspace = workspace
        self._prompter: callable | None = None

    def set_prompter(self, fn: callable) -> None:
        """Register a callback for interactive confirmation.

        fn(tool_name, args) -> bool  (True = allow, False = deny)
        """
        self._prompter = fn

    def check(self, tool_name: str, risk_level: str, args: dict) -> str | None:
        """Return None if allowed, or a denial reason string.

        Also performs workspace boundary checks for file-operating tools.
        """
        # 1. Mode-based access control
        denial = self._check_mode(tool_name, risk_level)
        if denial:
            return denial

        # 2. Workspace boundary for file tools
        if risk_level in (RISK_WRITE, RISK_READ):
            path_arg = args.get("path") or args.get("file") or args.get("filepath")
            if path_arg and risk_level == RISK_WRITE:
                boundary_err = check_workspace_boundary(path_arg, self.workspace)
                if boundary_err:
                    return boundary_err

        return None

    def _check_mode(self, tool_name: str, risk_level: str) -> str | None:
        risk = _RISK_ORDER.get(risk_level, 0)

        if self.mode == PermissionMode.DANGER:
            return None  # everything allowed

        if self.mode == PermissionMode.READONLY:
            if risk > _RISK_ORDER[RISK_READ]:
                return f"DENIED — mode is READONLY, cannot run '{tool_name}' (risk: {risk_level})"
            return None

        if self.mode == PermissionMode.WRITE:
            if risk > _RISK_ORDER[RISK_WRITE]:
                return f"DENIED — mode is WRITE, cannot run '{tool_name}' (risk: danger)"
            return None

        # PROMPT mode (default)
        if risk <= _RISK_ORDER[RISK_WRITE]:
            return None  # read + write auto-allowed

        # danger level → ask user
        if self._prompter:
            allowed = self._prompter(tool_name, args={})
            if allowed:
                return None
            return f"DENIED — user rejected '{tool_name}'"

        # no prompter registered → deny by default
        return f"DENIED — '{tool_name}' requires confirmation but no interactive session"

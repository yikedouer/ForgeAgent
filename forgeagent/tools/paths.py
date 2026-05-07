"""Path helpers shared by file tools."""

from __future__ import annotations

import os
from pathlib import Path


def active_workspace() -> str | None:
    """Return the active engine workspace when an engine is running."""
    try:
        from ..core.engine import _active_engine

        if _active_engine is not None:
            return _active_engine.settings.workspace
    except Exception:
        pass
    return None


def resolve_workspace_path(path: str) -> str:
    """Resolve relative tool paths against the active engine workspace."""
    expanded = Path(os.path.expanduser(path))
    if expanded.is_absolute():
        return str(expanded)

    workspace = active_workspace()
    if workspace is not None:
        return str(Path(workspace) / expanded)
    return str(expanded)


def active_workspace_boundary_error(path: str) -> str | None:
    """Return a denial message if path escapes the active workspace."""
    workspace = active_workspace()
    if workspace is None:
        return None
    if _is_active_plan_file(path):
        return None
    from ..core.permissions import check_workspace_boundary

    return check_workspace_boundary(path, workspace)


def _is_active_plan_file(path: str) -> bool:
    """Return True when *path* is the current plan-mode plan file."""
    try:
        from ..core.engine import _active_engine

        if _active_engine is None:
            return False
        mode = getattr(getattr(_active_engine, "enforcer", None), "mode", None)
        if getattr(mode, "value", None) != "plan":
            return False
        plan_file = getattr(getattr(_active_engine, "_plan", None), "plan_file_path", None)
        if not plan_file:
            return False
        return Path(path).expanduser().resolve() == Path(plan_file).expanduser().resolve()
    except Exception:
        return False

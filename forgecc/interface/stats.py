"""Workspace line-count statistics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".eggs", "*.egg-info", ".hatch",
}


@dataclass
class ExtensionStats:
    extension: str
    files: int = 0
    lines: int = 0


@dataclass
class WorkspaceStats:
    workspace: Path
    by_extension: dict[str, ExtensionStats] = field(default_factory=dict)
    total_files: int = 0
    total_lines: int = 0

    def sorted_extensions(self) -> list[ExtensionStats]:
        return sorted(
            self.by_extension.values(),
            key=lambda entry: entry.lines,
            reverse=True,
        )


def count_workspace_lines(workspace: str | os.PathLike[str]) -> WorkspaceStats:
    """Count readable text file lines grouped by extension."""
    root_path = Path(workspace)
    stats = WorkspaceStats(workspace=root_path)

    for root, dirs, files in os.walk(root_path):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for fname in files:
            ext = os.path.splitext(fname)[1] or fname
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as handle:
                    lines = sum(1 for _ in handle)
            except (OSError, UnicodeDecodeError):
                continue
            entry = stats.by_extension.setdefault(ext, ExtensionStats(ext))
            entry.lines += lines
            entry.files += 1
            stats.total_lines += lines
            stats.total_files += 1

    return stats

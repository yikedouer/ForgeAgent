"""Workspace line-count statistics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..filewalk import walk_files


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

    for _rel, fpath in walk_files(root_path):
        fname = os.path.basename(fpath)
        ext = os.path.splitext(fname)[1] or fname
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

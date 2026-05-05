"""Shared file tree traversal helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    ".hatch",
}


def walk_files(root: str | os.PathLike[str]) -> Iterator[tuple[str, str]]:
    """Yield ``(relative_path, absolute_path)`` for visible files in sorted order."""
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            name
            for name in dirnames
            if not _skip_dir(name)
        ]
        dirnames.sort()
        for filename in sorted(name for name in filenames if not name.startswith(".")):
            full_path = Path(dirpath) / filename
            yield os.path.relpath(full_path, root_path), str(full_path)


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info")

"""File and content search instruments (glob + grep)."""

from __future__ import annotations

import fnmatch
import os
import re

from ..toolkit import instrument


@instrument(
    name="glob_search",
    description=(
        "Find files matching a glob pattern. Returns up to `limit` paths, "
        "one per line. Searches recursively from the given root."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
            "root": {"type": "string", "description": "Directory to search from (default: cwd)"},
            "limit": {"type": "integer", "description": "Max results (default 200)"},
        },
        "required": ["pattern"],
    },
    readonly=True,
    risk_level="read",
)
def glob_search(pattern: str, root: str = ".", limit: int = 200) -> str:
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        return f"NOT A DIRECTORY: {root}"

    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # skip hidden dirs
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fname, pattern):
                hits.append(rel)
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break

    if not hits:
        return f"No files matching '{pattern}' under {root}"
    return "\n".join(hits)


@instrument(
    name="grep_search",
    description=(
        "Search file contents for a regex pattern. Returns matching lines "
        "with file path and line number context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "root": {"type": "string", "description": "Directory to search (default: cwd)"},
            "include": {"type": "string", "description": "Glob to filter filenames, e.g. '*.py'"},
            "limit": {"type": "integer", "description": "Max matching lines (default 100)"},
        },
        "required": ["pattern"],
    },
    readonly=True,
    risk_level="read",
)
def grep_search(
    pattern: str, root: str = ".", include: str = "", limit: int = 100
) -> str:
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        return f"NOT A DIRECTORY: {root}"

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"INVALID REGEX: {exc}"

    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if include and not fnmatch.fnmatch(fname, include):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if rx.search(line):
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= limit:
                                break
            except (OSError, PermissionError):
                continue
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    if not results:
        return f"No matches for /{pattern}/ under {root}"
    trailer = f"\n... (limited to {limit} results)" if len(results) == limit else ""
    return "\n".join(results) + trailer

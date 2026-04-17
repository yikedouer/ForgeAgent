"""File reading instrument with line numbering."""

from __future__ import annotations

import os

from ..toolkit import instrument

_MAX_READ_BYTES = 512_000  # refuse to read files larger than ~500 KB


@instrument(
    name="read_file",
    description=(
        "Read a file and return its contents with line numbers. "
        "Optionally restrict to a line range."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
            "from_line": {"type": "integer", "description": "Start line (1-based, inclusive)"},
            "to_line": {"type": "integer", "description": "End line (1-based, inclusive)"},
        },
        "required": ["path"],
    },
    readonly=True,
    risk_level="read",
)
def read_file(path: str, from_line: int = 0, to_line: int = 0) -> str:
    path = os.path.expanduser(path)

    if not os.path.isfile(path):
        return f"NOT FOUND: {path}"

    size = os.path.getsize(path)
    if size > _MAX_READ_BYTES:
        return f"FILE TOO LARGE ({size:,} bytes, limit {_MAX_READ_BYTES:,}): {path}"

    # detect binary
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except UnicodeDecodeError:
        return f"BINARY FILE (cannot display): {path}"

    # optional line range
    if from_line > 0:
        start = max(from_line - 1, 0)
        end = to_line if to_line > 0 else len(lines)
        lines = lines[start:end]
        offset = start
    else:
        offset = 0

    # format with line numbers
    numbered = []
    for i, line in enumerate(lines, start=offset + 1):
        numbered.append(f"{i:>6}| {line.rstrip()}")

    return "\n".join(numbered)

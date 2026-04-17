"""File writing instrument — create or overwrite a file."""

from __future__ import annotations

import os

from ..toolkit import instrument


@instrument(
    name="write_file",
    description=(
        "Write content to a file, creating parent directories as needed. "
        "Overwrites the file if it already exists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Target file path"},
            "content": {"type": "string", "description": "Full content to write"},
        },
        "required": ["path", "content"],
    },
    risk_level="write",
)
def write_file(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    existed = os.path.isfile(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

    line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
    verb = "Updated" if existed else "Created"
    return f"{verb} {path} ({line_count} lines)"

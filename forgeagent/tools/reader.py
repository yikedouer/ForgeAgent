"""文件读取工具，带行号输出。"""

from __future__ import annotations

import logging
import os

from ..toolkit import tool
from .paths import active_workspace_boundary_error, resolve_workspace_path

log = logging.getLogger(__name__)

_MAX_READ_BYTES = 512_000  # 拒绝读取超过 ~500 KB 的文件
_MAX_READ_OUTPUT_CHARS = 40_000


@tool(
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
    if not isinstance(path, str) or not path.strip():
        return "INVALID PATH: path must be non-empty."
    path = path.strip()
    path = resolve_workspace_path(path)
    boundary_err = active_workspace_boundary_error(path)
    if boundary_err:
        return boundary_err
    if (
        not isinstance(from_line, int)
        or isinstance(from_line, bool)
        or not isinstance(to_line, int)
        or isinstance(to_line, bool)
    ):
        return "INVALID RANGE: from_line and to_line must be non-negative."
    if from_line < 0 or to_line < 0:
        return "INVALID RANGE: from_line and to_line must be non-negative."
    if from_line > 0 and to_line > 0 and to_line < from_line:
        return "INVALID RANGE: to_line must be greater than or equal to from_line."
    log.debug("read_file: path=%s  from=%d  to=%d", path, from_line, to_line)

    if not os.path.isfile(path):
        log.debug("read_file: 文件不存在 %s", path)
        return f"NOT FOUND: {path}"

    size = os.path.getsize(path)
    if size > _MAX_READ_BYTES:
        return f"FILE TOO LARGE ({size:,} bytes, limit {_MAX_READ_BYTES:,}): {path}"

    # 检测二进制文件
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except UnicodeDecodeError:
        return f"BINARY FILE (cannot display): {path}"

    # 可选行范围
    if from_line > 0:
        start = max(from_line - 1, 0)
        end = to_line if to_line > 0 else len(lines)
        lines = lines[start:end]
        offset = start
    else:
        offset = 0

    # 格式化行号
    numbered = []
    for i, line in enumerate(lines, start=offset + 1):
        numbered.append(f"{i:>6}| {line.rstrip()}")

    output = "\n".join(numbered)
    if len(output) > _MAX_READ_OUTPUT_CHARS:
        half = _MAX_READ_OUTPUT_CHARS // 2
        output = (
            output[:half]
            + (
                f"\n\n... ({len(output) - _MAX_READ_OUTPUT_CHARS} chars omitted; "
                "use from_line/to_line for a narrower range) ...\n\n"
            )
            + output[-half:]
        )

    return output

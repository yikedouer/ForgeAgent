"""轻量类 YAML frontmatter 解析器。

解析 Markdown 文件顶部以 `---` 分隔的 key: value 块。
无需依赖 PyYAML，保持安装体积最小化。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Frontmatter:
    meta: dict[str, str]
    body: str


def parse_frontmatter(raw: str) -> Frontmatter:
    """解析包含可选 YAML frontmatter 的 Markdown 文件。"""
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return Frontmatter(meta={}, body=raw)

    closing = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing < 0:
        return Frontmatter(meta={}, body=raw)

    meta: dict[str, str] = {}
    for idx in range(1, closing):
        sep = lines[idx].find(":")
        if sep < 0:
            continue
        key = lines[idx][:sep].strip()
        val = lines[idx][sep + 1:].strip()
        if key:
            meta[key] = val

    body_start = closing + 1
    if body_start < len(lines) and lines[body_start] == "":
        body_start += 1
    body = "\n".join(lines[body_start:])
    return Frontmatter(meta=meta, body=body)

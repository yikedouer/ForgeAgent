"""轻量 YAML Frontmatter 解析器 — 零依赖。

处理记忆文件常用的 ``---\nkey: value\n---\nbody`` 格式。
仅支持单行 ``key: value`` 键值对（不支持嵌套或多行值）。
"""

from __future__ import annotations


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析以 ``---`` 分隔的 frontmatter 块。

    返回 ``(meta_dict, body_string)``。若未找到有效 frontmatter，
    *meta* 为空字典，*body* 为原始文本。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    meta: dict[str, str] = {}
    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            if key:
                meta[key] = value.strip()

    if end == -1:
        return {}, text

    body_start = end + 1
    if body_start < len(lines) and lines[body_start] == "":
        body_start += 1
    body = "\n".join(lines[body_start:])
    return meta, body


def format_frontmatter(meta: dict, body: str) -> str:
    """生成 Frontmatter 格式的字符串。"""
    lines = ["---"]
    for key, value in meta.items():
        key = " ".join(str(key).splitlines()).strip()
        if not key:
            continue
        safe_value = " ".join(str(value).splitlines())
        lines.append(f"{key}: {safe_value}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)

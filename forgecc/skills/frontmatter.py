"""Minimal YAML-like frontmatter parser.

Parses `---` delimited key: value blocks at the top of Markdown files.
No dependency on PyYAML — keeps the install footprint tiny.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Frontmatter:
    meta: dict[str, str]
    body: str


def parse_frontmatter(raw: str) -> Frontmatter:
    """Parse a Markdown file with optional YAML frontmatter."""
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

    body = "\n".join(lines[closing + 1:]).strip()
    return Frontmatter(meta=meta, body=body)

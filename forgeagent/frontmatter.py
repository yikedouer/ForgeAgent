"""Simple frontmatter parsing and formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Frontmatter:
    meta: dict[str, str]
    body: str

    def __iter__(self) -> Iterator[object]:
        yield self.meta
        yield self.body


def parse_frontmatter(text: str) -> Frontmatter:
    """Parse a leading ``---`` key-value frontmatter block."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return Frontmatter(meta={}, body=text)

    closing = -1
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing = idx
            break
    if closing < 0:
        return Frontmatter(meta={}, body=text)

    meta: dict[str, str] = {}
    for line in lines[1:closing]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            meta[key] = value.strip()

    body_start = closing + 1
    if body_start < len(lines) and lines[body_start] == "":
        body_start += 1
    return Frontmatter(meta=meta, body="\n".join(lines[body_start:]))


def format_frontmatter(meta: dict, body: str) -> str:
    """Render metadata and body into a frontmatter document."""
    lines = ["---"]
    for key, value in meta.items():
        key = " ".join(str(key).splitlines()).strip()
        if not key:
            continue
        safe_value = " ".join(str(value).splitlines())
        lines.append(f"{key}: {safe_value}")
    lines.extend(["---", "", body])
    return "\n".join(lines)

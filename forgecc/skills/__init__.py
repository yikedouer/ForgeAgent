"""Skill / playbook system — discovery, parsing, and execution."""

from .playbook import (
    Playbook,
    discover,
    find,
    invoke,
    resolve_template,
    invalidate_cache,
    describe_for_directive,
)
from .frontmatter import Frontmatter, parse_frontmatter

__all__ = [
    "Playbook", "discover", "find", "invoke", "resolve_template",
    "invalidate_cache", "describe_for_directive",
    "Frontmatter", "parse_frontmatter",
]

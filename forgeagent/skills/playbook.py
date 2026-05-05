"""Playbook — 技能发现、解析与执行。

"playbook" 是以 Markdown 文件存储的可复用提示词模板，
带有 YAML 风格的 frontmatter。Playbook 存放在固定目录中，
并作为可调用技能暴露给 LLM。

目录布局:
    .agents/skills/<name>/SKILL.md       (项目级，高优先级)
    ~/.forgeagent/skills/<name>/SKILL.md (用户级，低优先级)
    .claude/skills/<name>/SKILL.md       (兼容 Claude Code)
    .forgeagent/skills/<name>/SKILL.md   (兼容旧版项目配置)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..frontmatter import parse_frontmatter


# ── Playbook 定义 ─────────────────────────────────────

@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    hint: str               # LLM 何时使用的提示
    mode: str               # "inline" 或 "fork"
    user_invocable: bool
    allowed_tools: tuple[str, ...] | None
    template: str           # 含 $ARGUMENTS 占位符的原始提示词正文
    origin: str             # "project" | "user" | "compat"
    directory: str          # 技能目录的绝对路径


# ── 发现 ───────────────────────────────────────────────
# 按优先级扫描多个目录，同名技能由后扫描的覆盖。

_cache: list[Playbook] | None = None


def _scan_dir(base: Path, origin: str, out: dict[str, Playbook]) -> None:
    if not base.is_dir():
        return
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        pb = _load_one(skill_file, origin, str(child))
        if pb is not None:
            out[pb.name] = pb


def _tool_names(values: list[Any] | tuple[Any, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        name = value.strip().strip("\"'")
        if name:
            names.append(name)
    return tuple(names)


def _load_one(path: Path, origin: str, directory: str) -> Playbook | None:
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    meta = fm.meta
    name = meta.get("name") or path.parent.name

    # 解析 allowed-tools
    allowed: tuple[str, ...] | None = None
    raw_tools = meta.get("allowed-tools", "")
    if raw_tools:
        if raw_tools.startswith("["):
            try:
                parsed_tools = json.loads(raw_tools)
            except Exception:
                allowed = _tool_names(tuple(raw_tools.strip("[]").split(",")))
            else:
                if isinstance(parsed_tools, list):
                    allowed = _tool_names(parsed_tools)
        else:
            allowed = _tool_names(tuple(raw_tools.split(",")))

    return Playbook(
        name=name,
        description=meta.get("description", ""),
        hint=meta.get("when-to-use", "") or meta.get("when_to_use", ""),
        mode="fork" if meta.get("context") == "fork" else "inline",
        user_invocable=meta.get("user-invocable", "true").lower() != "false",
        allowed_tools=allowed if allowed else None,
        template=fm.body,
        origin=origin,
        directory=directory,
    )


def discover() -> list[Playbook]:
    """返回所有已发现的 playbook，首次调用后缓存。"""
    global _cache
    if _cache is not None:
        return _cache

    collected: dict[str, Playbook] = {}

    # 用户级（最低优先级）
    _scan_dir(Path.home() / ".forgeagent" / "skills", "user", collected)
    _scan_dir(Path.home() / ".agents" / "skills", "user", collected)

    # 兼容: .claude/skills
    _scan_dir(Path.cwd() / ".claude" / "skills", "compat", collected)

    # 项目级（最高优先级）
    _scan_dir(Path.cwd() / ".forgeagent" / "skills", "project", collected)
    _scan_dir(Path.cwd() / ".agents" / "skills", "project", collected)

    _cache = list(collected.values())
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None


# ── 解析 ──────────────────────────────────────────────

def find(name: str) -> Playbook | None:
    for pb in discover():
        if pb.name == name:
            return pb
    return None


def resolve_template(pb: Playbook, arguments: str) -> str:
    """替换 $ARGUMENTS / ${ARGUMENTS} 和 ${SKILL_DIR}。"""
    text = pb.template
    text = re.sub(r"\$ARGUMENTS|\$\{ARGUMENTS\}", arguments, text)
    text = text.replace("${SKILL_DIR}", pb.directory)
    return text


def invoke(name: str, arguments: str = "") -> dict[str, Any] | None:
    """准备 playbook 以便执行。未找到则返回 None。"""
    pb = find(name)
    if pb is None:
        return None
    return {
        "prompt": resolve_template(pb, arguments),
        "mode": pb.mode,
        "allowed_tools": pb.allowed_tools,
    }


# ── 系统提示词片段 ──────────────────────────────────

def describe_for_directive() -> str:
    """为系统提示词生成描述可用技能的文本片段。"""
    playbooks = discover()
    if not playbooks:
        return ""

    parts = ["# Registered Skills", ""]
    manual = [p for p in playbooks if p.user_invocable]
    auto = [p for p in playbooks if not p.user_invocable]

    if manual:
        parts.append("Skills the user can invoke with /<name>:")
        for p in manual:
            parts.append(f"  - /{p.name}: {p.description}")
            if p.hint:
                parts.append(f"    Hint: {p.hint}")
        parts.append("")

    if auto:
        parts.append("Skills for automatic use (call via the skill tool):")
        for p in auto:
            parts.append(f"  - {p.name}: {p.description}")
            if p.hint:
                parts.append(f"    Hint: {p.hint}")
        parts.append("")

    return "\n".join(parts)

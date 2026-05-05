"""动态系统提示词组装。

系统指令在每次 LLM 调用前重建，以始终反映当前环境。
它编织了：

  1. 角色设定——Agent 是什么以及应如何行为
  2. 环境快照——操作系统、当前目录、时间戳、git 分支
  3. 工具清单——可用工具的简洁列表
  4. 项目规则——FORGECC.md / CLAUDE.md 的内容（如有）
"""

from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime

from ..core.settings import Settings
from .. import toolkit
from ..skills import playbook
from ..memory.store import load_memory_index, get_memory_dir
from ..core.subagent import build_agent_descriptions


def _git_branch(workspace: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _project_rules(workspace: str) -> str:
    """从知名文件加载项目级指导。"""
    candidates = ["FORGECC.md", "CLAUDE.md", ".forgecc/rules.md"]
    for name in candidates:
        path = os.path.join(workspace, name)
        if os.path.isfile(path):
            try:
                content = open(path, "r", encoding="utf-8").read(8_000)
                return f"\n<project_rules source=\"{name}\">\n{content}\n</project_rules>\n"
            except Exception:
                continue
    return ""


def _instrument_manifest() -> str:
    """每个工具一行的摘要，用于系统提示词。"""
    lines = []
    for spec in toolkit.catalog().values():
        lines.append(f"  - {spec.name}: {spec.description}")
    return "\n".join(lines)


def build(settings: Settings, *, plan_mode_prompt: str | None = None) -> str:
    """组装完整的系统指令。

    提供 *plan_mode_prompt* 时（计划模式活跃），它会追加到
    指令末尾，用只读约束覆盖普通操作规则。
    """

    branch = _git_branch(settings.workspace)
    rules = _project_rules(settings.workspace)
    instruments = _instrument_manifest()

    parts = [
        "You are ForgeCC, an interactive coding agent that helps users with "
        "software engineering tasks. Use the instructions below and the tools "
        "available to you to assist the user.",
        "",
        "# System",
        "- All text you output outside of tool use is displayed to the user. "
        "Use Github-flavored markdown for formatting.",
        "- Tool results and user messages may include system tags. "
        "They bear no direct relation to the specific tool results or "
        "user messages in which they appear.",
        "- The system will automatically compress prior messages as it "
        "approaches context limits. Your conversation is not limited "
        "by the context window.",
        "",
        "# Doing tasks",
        "- The user will primarily request software engineering tasks: "
        "solving bugs, adding features, refactoring, explaining code, etc. "
        "When given an unclear instruction, consider it in the context of "
        "the current working directory.",
        "- Do not propose changes to code you haven't read. If a user asks "
        "about or wants you to modify a file, read it first.",
        "- Do not create files unless absolutely necessary. Prefer editing "
        "an existing file to creating a new one.",
        "- If an approach fails, diagnose why before switching tactics \u2014 "
        "read the error, check your assumptions, try a focused fix. "
        "Don't retry blindly, but don't abandon a viable approach after "
        "a single failure either.",
        "- Avoid over-engineering. Only make changes that are directly "
        "requested or clearly necessary. Keep solutions simple and focused.",
        "  - Don't add features, refactor code, or make 'improvements' "
        "beyond what was asked.",
        "  - Don't add error handling for scenarios that can't happen. "
        "Only validate at system boundaries.",
        "  - Don't create helpers or abstractions for one-time operations.",
        "- When the user asks for code examples, explanations, or "
        "demonstrations, show the code directly in your response text. "
        "Only create/edit files when the user explicitly wants to modify "
        "the project.",
        "",
        "# Executing actions with care",
        "- Freely take local, reversible actions like editing files or "
        "running tests.",
        "- For actions that are hard to reverse or affect shared systems, "
        "check with the user before proceeding.",
        "- Examples warranting confirmation: deleting files/branches, "
        "force-pushing, pushing code, creating/commenting on PRs, "
        "modifying CI/CD pipelines.",
        "- When you encounter an obstacle, do not use destructive actions "
        "as a shortcut. Identify root causes rather than bypassing safety "
        "checks.",
        "",
        "# Using your tools",
        "- Do NOT use shell to run commands when a dedicated tool exists:",
        "  - read_file instead of cat/head/tail",
        "  - edit_file instead of sed/awk",
        "  - write_file instead of echo redirection",
        "  - glob_search instead of find/ls",
        "  - grep_search instead of grep/rg",
        "- You can call multiple tools in a single response. Make all "
        "independent tool calls in parallel for efficiency.",
        "- Use the agent tool with specialized agents when the task "
        "matches the agent's description. Avoid duplicating work that "
        "subagents are already doing.",
        "",
        "# Tone and style",
        "- Only use emojis if the user explicitly requests it.",
        "- Your responses should be short and concise.",
        "- When referencing code, include file_path:line_number.",
        "",
        "# Output efficiency",
        "- Go straight to the point. Try the simplest approach first.",
        "- Keep text output brief and direct. Lead with the answer or "
        "action, not the reasoning.",
        "- Focus text output on: decisions needing user input, high-level "
        "status updates, errors or blockers that change the plan.",
        "- If you can say it in one sentence, don't use three.",
        "",
        "# Environment",
        f"  Working directory: {settings.workspace}",
        f"  Date: {datetime.now().strftime('%Y-%m-%d')}",
        f"  Platform: {platform.system()} {platform.machine()}",
    ]

    if branch:
        parts.append(f"  Git branch: {branch}")

    parts += [
        "",
        "# Available instruments",
        instruments,
    ]

    if rules:
        parts.append(rules)

    memory_section = _memory_section(settings.workspace)
    if memory_section:
        parts.append(memory_section)

    skill_section = playbook.describe_for_directive()
    if skill_section:
        parts.append("")
        parts.append(skill_section)

    agent_desc = build_agent_descriptions()
    if agent_desc:
        parts.append(agent_desc)

    if plan_mode_prompt:
        parts.append(plan_mode_prompt)

    return "\n".join(parts)


def _memory_section(workspace: str) -> str:
    """组装 8 节记忆行为指令 + MEMORY.md 索引。

    对齐 claw-code 的 ``buildMemoryLines()`` 结构。
    """
    mem_dir = get_memory_dir(workspace)
    index = load_memory_index(workspace)
    dir_exists = mem_dir.exists() and any(
        f.suffix == ".md" and f.name != "MEMORY.md" for f in mem_dir.iterdir()
    )

    parts: list[str] = []

    # §1 — 持久化介绍 + 目录指导
    parts.append(
        "# Persistent Memory\n"
        f"You have a persistent, file-based memory system at `{mem_dir}`.\n"
        "Memories survive across sessions — use them for information that cannot "
        "be derived from the current project state."
    )
    if dir_exists:
        parts.append(
            "The memory directory already exists and contains files — "
            "do NOT check whether it exists before reading or writing."
        )

    # §2 — 明确的用户操作
    parts.append(
        '## Explicit Actions\n'
        '- When the user says "remember" / "save this", immediately use '
        '`memory_save` to persist the information.\n'
        '- When the user says "forget" / "delete memory", use `memory_list` '
        'to find the entry, then `memory_delete` to remove it.\n'
        '- When the user says "what do you remember", use `memory_list` and '
        'summarize what you have stored.'
    )

    # §3 — 四类型封闭分类
    parts.append(
        '## Memory Types (closed taxonomy — use exactly one)\n'
        '- **user**: Identity, preferences, knowledge level, communication style.\n'
        '- **feedback**: Corrections or guidance from the user.  Always include '
        '*why* it matters and *how* to apply it.\n'
        '- **project**: Ongoing work, goals, deadlines, architectural decisions.  '
        'Use absolute dates ("2025-01-15"), never relative ("next week").\n'
        '- **reference**: Pointers to external resources — URLs, dashboards, API docs.'
    )

    # §4 — 不应保存的内容
    parts.append(
        '## Do NOT Save\n'
        '- Code patterns or architecture (read the code instead).\n'
        '- Git history (use `git log`).\n'
        '- Content already in project rules (FORGECC.md / CLAUDE.md).\n'
        '- Ephemeral task details that will not matter next session.'
    )

    # §5 — 如何保存
    parts.append(
        '## How to Save\n'
        'Use the `memory_save` tool — do NOT use `write_file` for memories.\n'
        'The `description` field is the primary field used for semantic recall; '
        'make it specific and searchable (e.g. "User prefers Ruff over Flake8 '
        'for linting", not "linting preference").'
    )

    # §6 — 访问规则
    parts.append(
        '## When to Access Memories\n'
        '1. When you *know* a memory is relevant to the current task, '
        'proactively consult it — do not wait for the user to ask.\n'
        '2. When the user explicitly asks you to recall, you MUST access '
        'memories.\n'
        '3. If the user says "ignore memories", treat them as nonexistent '
        'for that turn.'
    )

    # §7 — 信任验证
    parts.append(
        '## Trust Verification\n'
        'Memories are point-in-time snapshots, not live state.\n'
        '- If a memory cites a file path, use `read_file` to verify it still exists.\n'
        '- If a memory references a function or class name, use `grep` to confirm '
        'it is still present.\n'
        '- Never assert a memory\'s claims as current fact without verification.'
    )

    # §8 — 当前记忆索引
    if index:
        parts.append(f"## Current Memory Index\n{index}")
    else:
        parts.append("(No memories saved yet.)")

    return "\n\n".join(parts)

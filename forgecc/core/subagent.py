"""子 Agent 类型系统与自定义 Agent 发现。

提供内置 Agent 类型（explore / plan / verification / general），
每种类型配有专属系统提示词和工具集过滤，同时支持通过
``~/.forgecc/agents/*.md`` 和 ``<workspace>/.forgecc/agents/*.md``
发现用户自定义 Agent。

对齐 claw-code 的多层扫描路径设计：
  * 环境变量 ``FORGECC_AGENTS_DIR`` 可覆盖用户级路径
  * 兼容 ``.claude/agents/`` 目录（方便迁移）
  * 项目级优先于用户级（同名覆盖）

参照 claude-code 的 ``subagent.ts`` fork-return 架构实现。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..frontmatter import parse_frontmatter

# ── 只读工具白名单 ──────────────────────────────────────────
# explore 和 plan 子 Agent 允许使用的工具集。
# 有意包含 ``shell``，用于只读命令（git log、find 等）；
# 系统提示词负责约束其使用范围。

READ_ONLY_TOOLS: set[str] = {
    "read_file",
    "glob_search",
    "grep_search",
    "shell",
}

# verification 子 Agent 允许使用的工具集。
# 在只读工具基础上增加 shell（已包含）用于执行测试命令。
# 不允许写文件——验证 Agent 只负责「确认」而非「修改」。
VERIFICATION_TOOLS: set[str] = {
    "read_file",
    "glob_search",
    "grep_search",
    "shell",
}

RECURSIVE_AGENT_TOOLS = {"agent", "team"}


def _parse_allowed_tools(raw: str) -> set[str] | None:
    names = {name.strip() for name in raw.split(",") if name.strip()}
    return names or None


def _load_agents_from_dir(
    directory: Path,
    agents: dict[str, dict[str, Any]],
) -> None:
    """Load ``*.md`` agent definition files from a directory."""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if entry.suffix != ".md":
            continue
        try:
            raw = entry.read_text(encoding="utf-8")
            parsed = parse_frontmatter(raw)
            meta, body = parsed.meta, parsed.body
            name = meta.get("name") or entry.stem
            allowed_tools: set[str] | None = None
            if "allowed-tools" in meta:
                allowed_tools = _parse_allowed_tools(meta["allowed-tools"])
            agents[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "allowed_tools": allowed_tools,
                "system_prompt": body,
            }
        except Exception:
            pass


def discover_custom_agents() -> dict[str, dict[str, Any]]:
    """Load custom agents from user, env override, and project directories."""
    agents: dict[str, dict[str, Any]] = {}
    home = Path.home()
    cwd = Path.cwd()

    _load_agents_from_dir(home / ".claude" / "agents", agents)
    _load_agents_from_dir(home / ".forgecc" / "agents", agents)
    env_dir = os.environ.get("FORGECC_AGENTS_DIR")
    if env_dir:
        _load_agents_from_dir(Path(env_dir).expanduser(), agents)

    _load_agents_from_dir(cwd / ".claude" / "agents", agents)
    _load_agents_from_dir(cwd / ".forgecc" / "agents", agents)

    return agents


def resolve_sub_agent_tool_names(
    available_tools: Iterable[str],
    configured_tools: set[str] | None,
    allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
) -> set[str]:
    """Resolve the tool names a sub-agent may use."""
    if configured_tools is None:
        tool_names = set(available_tools)
    else:
        tool_names = set(configured_tools)

    if allowed_tools is not None:
        tool_names &= set(allowed_tools)

    return tool_names - RECURSIVE_AGENT_TOOLS


# ── 内置系统提示词 ──────────────────────────────────────────

EXPLORE_PROMPT = """\
You are a file search specialist for ForgeCC. You excel at \
thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE — NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no write_file, touch, or file creation of any kind)
- Modifying existing files (no edit_file operations)
- Deleting files (no rm or deletion)
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- Use glob_search for broad file pattern matching
- Use grep_search for searching file contents with regex
- Use read_file when you know the specific file path you need to read
- Use shell for read-only commands like git log, find, wc, head, etc.
- Adapt your search approach based on the thoroughness level specified \
by the caller

NOTE: You are meant to be a fast agent that returns output as quickly \
as possible. In order to achieve this you must:
- Make efficient use of the tools at your disposal: be smart about \
how you search for files and implementations
- Wherever possible try to spawn multiple parallel tool calls for \
grepping and reading files

Complete the search request efficiently and report your findings clearly."""

PLAN_PROMPT = """\
You are a Plan agent — a READ-ONLY sub-agent specialized for \
designing implementation plans.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. You only have access to read_file, glob_search, \
grep_search, and shell.
- Do NOT attempt to modify any files.

Your job:
- Analyze the codebase to understand the current architecture
- Design a step-by-step implementation plan
- Identify critical files that need modification
- Consider architectural trade-offs

Return a structured plan with:
1. Summary of current state
2. Step-by-step implementation steps
3. Critical files for implementation
4. Potential risks or considerations"""

VERIFICATION_PROMPT = """\
You are a Verification agent — a sub-agent specialized for \
validating code changes, running tests, and confirming correctness.

IMPORTANT CONSTRAINTS:
- Your job is to VERIFY, not to FIX. If something is broken, \
report the failure clearly — do NOT attempt to edit files.
- You have access to read_file, glob_search, grep_search, and shell.
- Use shell to run tests (pytest, npm test, cargo test, etc.), \
linters, type checkers, and build commands.

Your workflow:
1. Understand what needs to be verified (test suite, specific file, build).
2. Run the relevant commands via shell.
3. Read output carefully — distinguish warnings from errors.
4. Report a clear pass/fail verdict with evidence.

Output format:
- Start with a one-line verdict: PASS ✓ or FAIL ✗
- List each check performed and its result
- For failures: include the exact error message and file:line
- Keep the report concise — the caller needs actionable info, not logs."""

GENERAL_PROMPT = """\
You are an agent for ForgeCC. Given the user's message, you should \
use the tools available to complete the task. Complete the task \
fully — don't gold-plate, but don't leave it half-done. When you \
complete the task, respond with a concise report covering what was \
done and any key findings — the caller will relay this to the user, \
so it only needs the essentials.

Your strengths:
- Searching for code, configurations, and patterns across large codebases
- Analyzing multiple files to understand system architecture
- Investigating complex questions that require exploring many files
- Performing multi-step research and implementation tasks

Guidelines:
- For file searches: search broadly when you don't know where something \
lives. Use read_file when you know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search \
strategies if the first doesn't yield results.
- Be thorough: Check multiple locations, consider different naming \
conventions, look for related files.
- NEVER create files unless they're absolutely necessary for achieving \
your goal. ALWAYS prefer editing an existing file to creating a new one."""


# ── 自定义 Agent 发现 ────────────────────────────────────────

_cached_custom_agents: dict[str, dict[str, Any]] | None = None


def _discover_custom_agents() -> dict[str, dict[str, Any]]:
    """从多层目录加载自定义 Agent。

    扫描顺序（低优先级 → 高优先级，后者覆盖前者）：
      1. ``~/.claude/agents/``  — 兼容 Claude Code
      2. ``~/.forgecc/agents/`` — ForgeCC 用户级默认
      3. ``$FORGECC_AGENTS_DIR``— 环境变量覆盖用户级
      4. ``<cwd>/.claude/agents/``  — 项目级兼容
      5. ``<cwd>/.forgecc/agents/`` — 项目级默认（最高优先级）

    首次扫描后结果将被缓存。
    """
    global _cached_custom_agents
    if _cached_custom_agents is not None:
        return _cached_custom_agents

    _cached_custom_agents = discover_custom_agents()
    return _cached_custom_agents


# ── 主配置函数 ───────────────────────────────────────────────


def get_sub_agent_config(agent_type: str) -> dict[str, Any]:
    """返回指定 Agent 类型的 ``{system_prompt, tool_names}``。

    ``tool_names`` 是子 Agent 允许使用的工具名集合。
    ``None`` 表示"除 *agent* 外的所有工具"
    （由调用方负责排除，以防递归嵌套）。
    """
    # 优先查找自定义 Agent
    custom = _discover_custom_agents().get(agent_type)
    if custom:
        return {
            "system_prompt": custom["system_prompt"],
            "tool_names": custom["allowed_tools"],  # None 表示除 agent 外全部
        }

    if agent_type == "explore":
        return {"system_prompt": EXPLORE_PROMPT, "tool_names": READ_ONLY_TOOLS}
    elif agent_type == "plan":
        return {"system_prompt": PLAN_PROMPT, "tool_names": READ_ONLY_TOOLS}
    elif agent_type in ("verification", "verify"):
        return {"system_prompt": VERIFICATION_PROMPT, "tool_names": VERIFICATION_TOOLS}
    else:  # general（默认）
        return {"system_prompt": GENERAL_PROMPT, "tool_names": None}


# ── 系统提示词注入辅助 ──────────────────────────────────────


def get_available_agent_types() -> list[dict[str, str]]:
    """列出所有可用的 Agent 类型（内置 + 自定义）。"""
    types = [
        {"name": "explore", "description": "Fast, read-only codebase search and exploration"},
        {"name": "plan", "description": "Read-only analysis with structured implementation plans"},
        {"name": "verification", "description": "Run tests, linters and builds to verify code changes"},
        {"name": "general", "description": "Full tools for independent task completion"},
    ]
    for name, defn in _discover_custom_agents().items():
        types.append({"name": name, "description": defn["description"]})
    return types


def build_agent_descriptions() -> str:
    """返回列出自定义 Agent 类型的系统提示词片段。

    当仅有内置类型时返回空字符串
    （内置类型已在 agent 工具 schema 中描述）。
    """
    custom = _discover_custom_agents()
    if not custom:
        return ""

    lines = ["\n# Custom Agent Types", ""]
    for name, defn in custom.items():
        lines.append(f"- **{name}**: {defn['description']}")
    lines.append(
        "\nUse the agent tool with the type parameter set to one of "
        "these names to spawn a custom sub-agent."
    )
    return "\n".join(lines)


def reset_agent_cache() -> None:
    """清除自定义 Agent 缓存（用于测试）。"""
    global _cached_custom_agents
    _cached_custom_agents = None

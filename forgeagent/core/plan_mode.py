"""Plan Mode — 只读规划阶段与 4 选项审批工作流。

让 Agent 在做任何修改之前先探索代码并将结构化计划写入专用文件。
工作流：

  enter_plan_mode → Agent 读代码 → 写 plan 文件 → exit_plan_mode
  → 用户审查 → 4 选项审批 → 恢复执行（或继续规划）

Plan 文件持久化到 ~/.forgeagent/plans/，可在上下文清除后幸存。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, TypedDict

from ..context.checkpoint import session_file_stem
from .permissions import PermissionMode, PermissionEnforcer


# ── 常量 ────────────────────────────────────────────────

PLAN_TOOL_NAMES: set[str] = {"enter_plan_mode", "exit_plan_mode"}

PLAN_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "enter_plan_mode",
        "description": (
            "Enter plan mode to switch to a read-only planning phase. "
            "In plan mode, you can only read files and write to the plan file. "
            "Use this when you need to explore the codebase and design an "
            "implementation plan before making changes."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "exit_plan_mode",
        "description": (
            "Exit plan mode after you have finished writing your plan "
            "to the plan file. The user will review and approve the plan "
            "before you proceed with implementation."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]

# plan 模式下允许写入的工具（仅限 plan 文件）
EDIT_TOOL_NAMES: set[str] = {"write_file", "edit_file"}


# ── 类型 ──────────────────────────────────────────────────

class PlanApprovalResult(TypedDict, total=False):
    choice: str           # "clear-and-execute" | "execute" | "manual-execute" | "keep-planning"
    feedback: str | None  # user feedback when choice == "keep-planning"


PlanApprovalFn = Callable[[str], Awaitable[PlanApprovalResult]]


# ── Plan 文件管理 ──────────────────────────────────────

def generate_plan_file_path(session_id: str) -> Path:
    """返回 ``~/.forgeagent/plans/plan-{session_id}.md``，自动创建目录。"""
    safe_session_id = session_file_stem(session_id)
    plans_dir = Path(
        os.environ.get("FORGEAGENT_PLANS_DIR", str(Path.home() / ".forgeagent" / "plans"))
    ).expanduser()
    plans_dir.mkdir(parents=True, exist_ok=True)
    return plans_dir / f"plan-{safe_session_id}.md"


# ── 系统提示词构建 ────────────────────────────────────

def build_plan_mode_prompt(plan_file_path: str) -> str:
    """构建追加到系统指令的 Plan Mode 段落。

    三个职责：
      1. 约束行为 — 禁止编辑和 shell（plan 文件除外）。
      2. 声明 plan 文件 — 唯一可写的文件路径。
      3. 定义 4 步工作流 — 探索 → 设计 → 写计划 → 退出。
    """
    return f"""

# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), \
run non-readonly tools, or make any changes to the system.

## Plan File: {plan_file_path}
Write your plan incrementally to this file using write_file or edit_file. \
This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, grep_search, glob_search.
2. **Design**: Design your implementation approach.
3. **Write Plan**: Write a structured plan to the plan file including:
   - **Objective**: What the user wants and what is out of scope
   - **Current State**: Relevant files, existing behavior, and repository state
   - **Steps**: Ordered implementation steps with critical file paths
   - **Risks**: User-change conflicts, compatibility issues, or security concerns
   - **Verification**: Exact commands or checks that should prove the changes
   - **Rollback**: How to back out if the plan fails
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. \
Do NOT ask the user to approve — exit_plan_mode handles that."""


class PlanModeController:
    """Manage plan mode state, approval handling, and plan-mode call filtering."""

    def __init__(
        self,
        *,
        session_id: Callable[[], str],
        enforcer: PermissionEnforcer,
        transcript: list[dict],
        lookup_tool: Callable[[str], Any] | None = None,
    ):
        self.session_id = session_id
        self.enforcer = enforcer
        self.transcript = transcript
        self.lookup_tool = lookup_tool
        self.pre_plan_mode: str | None = None
        self.plan_file_path: str | None = None
        self.approval_fn: PlanApprovalFn | None = None
        self.context_cleared = False

    def set_approval_fn(self, fn: PlanApprovalFn) -> None:
        self.approval_fn = fn

    def toggle(self) -> str:
        if self.enforcer.mode == PermissionMode.PLAN:
            self.enforcer.mode = PermissionMode(self.pre_plan_mode or "prompt")
            self.pre_plan_mode = None
            self.plan_file_path = None
            return self.enforcer.mode.value

        self.pre_plan_mode = self.enforcer.mode.value
        self.enforcer.mode = PermissionMode.PLAN
        self.plan_file_path = str(generate_plan_file_path(self.session_id()))
        return "plan"

    def execute_tool(self, name: str) -> str:
        if name == "enter_plan_mode":
            if self.enforcer.mode == PermissionMode.PLAN:
                return "Already in plan mode."
            self.pre_plan_mode = self.enforcer.mode.value
            self.enforcer.mode = PermissionMode.PLAN
            self.plan_file_path = str(generate_plan_file_path(self.session_id()))
            return (
                f"Entered plan mode. You are now in read-only mode.\n\n"
                f"Your plan file: {self.plan_file_path}\n"
                f"Write your plan to this file. This is the only file you can edit.\n\n"
                f"When your plan is complete, call exit_plan_mode."
            )

        if name == "exit_plan_mode":
            if self.enforcer.mode != PermissionMode.PLAN:
                return "Not in plan mode."

            plan_content = "(No plan file found)"
            if self.plan_file_path and Path(self.plan_file_path).exists():
                plan_content = Path(self.plan_file_path).read_text(encoding="utf-8")

            if self.approval_fn:
                result = asyncio.get_event_loop().run_until_complete(
                    self.approval_fn(plan_content)
                )
                return self.handle_approval(result, plan_content)

            self.enforcer.mode = PermissionMode(self.pre_plan_mode or "prompt")
            self.pre_plan_mode = None
            saved_path = self.plan_file_path
            self.plan_file_path = None
            return (
                f"Exited plan mode. Permission mode restored to: "
                f"{self.enforcer.mode.value}\n\n"
                f"## Your Plan:\n{plan_content}"
            )

        return f"Unknown plan mode tool: {name}"

    def handle_approval(self, result: dict, plan_content: str) -> str:
        if not isinstance(result, dict):
            result = {}
        choice = result.get("choice")

        if choice not in {
            "clear-and-execute",
            "execute",
            "manual-execute",
        }:
            feedback = result.get("feedback") or "Please revise the plan."
            return (
                f"User rejected the plan and wants to keep planning.\n\n"
                f"User feedback: {feedback}\n\n"
                f"Please revise your plan based on this feedback. "
                f"When done, call exit_plan_mode again."
            )

        target_mode = "danger" if choice in ("clear-and-execute", "execute") else (
            self.pre_plan_mode or "prompt"
        )

        self.enforcer.mode = PermissionMode(target_mode)
        self.pre_plan_mode = None
        saved_path = self.plan_file_path
        self.plan_file_path = None

        if choice == "clear-and-execute":
            self.transcript.clear()
            self.context_cleared = True
            return (
                f"User approved the plan. Context was cleared. "
                f"Permission mode: {target_mode}\n\n"
                f"Plan file: {saved_path}\n\n"
                f"## Approved Plan:\n{plan_content}\n\n"
                f"Proceed with implementation."
            )

        return (
            f"User approved the plan. Permission mode: {target_mode}\n\n"
            f"## Approved Plan:\n{plan_content}\n\n"
            f"Proceed with implementation."
        )

    def filter_calls(
        self,
        calls: list[tuple[str, str, object]],
    ) -> list[tuple[str, str, object]]:
        allowed: list[tuple[str, str, object]] = []
        plan_path = str(Path(self.plan_file_path).resolve()) if self.plan_file_path else ""

        for idx, call in enumerate(calls):
            if not isinstance(call, tuple) or len(call) != 3:
                self.transcript.append({
                    "role": "tool",
                    "tool_call_id": f"call_{idx}",
                    "content": "[plan mode] Invalid tool call: expected (call_id, name, args).",
                })
                continue
            call_id, fn_name, args = call
            if isinstance(fn_name, str) and fn_name in EDIT_TOOL_NAMES:
                tool_call_id = _tool_call_id(call_id, f"call_{idx}")
                if not isinstance(args, dict):
                    self.transcript.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": f"[plan mode] Blocked: {fn_name} with invalid arguments. "
                                   f"Only the plan file can be edited.",
                    })
                    continue
                target = args.get("path") or args.get("file_path") or ""
                try:
                    resolved = str(Path(target).expanduser().resolve())
                except Exception:
                    resolved = target
                if resolved == plan_path:
                    spec = self.lookup_tool(fn_name) if self.lookup_tool else None
                    if spec:
                        try:
                            output = spec.fn(**args)
                        except Exception as exc:
                            output = f"Error: {exc}"
                        self.transcript.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": output,
                        })
                    else:
                        allowed.append((call_id, fn_name, args))
                else:
                    self.transcript.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": f"[plan mode] Blocked: {fn_name} on '{target}'. "
                                   f"Only the plan file can be edited.",
                    })
            elif isinstance(fn_name, str) and fn_name == "shell":
                self.transcript.append({
                    "role": "tool",
                    "tool_call_id": _tool_call_id(call_id, f"call_{idx}"),
                    "content": "[plan mode] Shell commands are blocked in plan mode.",
                })
            else:
                allowed.append((call_id, fn_name, args))

        return allowed


def _tool_call_id(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback

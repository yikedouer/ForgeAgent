"""Team 工具——批量并行生成子 Agent。

对齐 claw-code 的 ``TeamCreate`` 工具设计：
一次调用创建多个子 Agent 并在独立线程中并行执行，
所有结果汇总后返回给父对话。适用于需要同时完成多个
独立子任务的场景（如同时搜索多个目录、并行验证多个模块等）。
"""

from __future__ import annotations

import json

from ..toolkit import tool

_VALID_AGENT_TYPES = {"explore", "plan", "verification", "general"}


def _team_result_text(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "(no output)"


def _team_result_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


@tool(
    name="team",
    description=(
        "Spawn multiple sub-agents in parallel. Each agent runs in a "
        "separate thread with its own context window. Use this when you "
        "need to perform multiple independent tasks concurrently."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agents": {
                "type": "array",
                "description": (
                    "List of sub-agent definitions. Each entry is an object "
                    "with 'type' (explore/plan/verification/general), "
                    "'description' (short task label), and 'prompt' "
                    "(detailed instructions)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "explore", "plan", "verification", "general",
                            ],
                            "description": (
                                "Sub-agent type. Defaults to 'general'."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": "Short 3-5 word task description.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Detailed, self-contained task instructions."
                            ),
                        },
                        "model": {
                            "type": "string",
                            "description": (
                                "Override model for this agent. "
                                "Omit to use the parent's model."
                            ),
                        },
                    },
                    "required": ["description", "prompt"],
                },
            },
        },
        "required": ["agents"],
    },
    risk_level="write",
)
def team(agents: list[dict]) -> str:
    """批量并行执行多个子 Agent，返回汇总结果。"""
    if not agents or not isinstance(agents, list):
        return "Error: 'agents' must be a non-empty list."

    if len(agents) > 8:
        return "Error: team supports at most 8 concurrent sub-agents."

    normalized_agents: list[dict] = []
    for i, spec in enumerate(agents, 1):
        if not isinstance(spec, dict):
            return f"INVALID AGENT: agents[{i}] must be an object."
        if (
            not isinstance(spec.get("description"), str)
            or not spec["description"].strip()
        ):
            return f"INVALID DESCRIPTION: agents[{i}] description must be non-empty."
        if (
            not isinstance(spec.get("prompt"), str)
            or not spec["prompt"].strip()
        ):
            return f"INVALID PROMPT: agents[{i}] prompt must be non-empty."
        agent_type = spec.get("type", "general")
        if not isinstance(agent_type, str):
            allowed = ", ".join(sorted(_VALID_AGENT_TYPES))
            return f"INVALID TYPE: agents[{i}] type must be one of: {allowed}."
        agent_type = agent_type.strip()
        if agent_type not in _VALID_AGENT_TYPES:
            allowed = ", ".join(sorted(_VALID_AGENT_TYPES))
            return f"INVALID TYPE: agents[{i}] type must be one of: {allowed}."
        normalized = dict(spec)
        normalized["type"] = agent_type
        normalized["description"] = spec["description"].strip()
        normalized["prompt"] = spec["prompt"].strip()
        if spec.get("model") is not None:
            if not isinstance(spec["model"], str):
                return f"INVALID MODEL: agents[{i}] model must be a string when provided."
            if not spec["model"].strip():
                normalized["model"] = None
            else:
                normalized["model"] = spec["model"].strip()
        normalized_agents.append(normalized)

    # 延迟导入以打破循环依赖
    from ..core.engine import Engine

    results = Engine.execute_sub_agents_parallel(normalized_agents)

    # 格式化汇总报告
    parts: list[str] = [f"## Team Results ({len(results)} agents)\n"]
    for i, r in enumerate(results, 1):
        if not isinstance(r, dict):
            r = {}
        description = r.get("description")
        if not isinstance(description, str):
            description = ""
        result_text = _team_result_text(r.get("result"))
        lowered = result_text.lower()
        failed = "(failed" in lowered or "thread error" in lowered
        status = "✗" if failed else "✓"
        parts.append(
            f"### {status} Agent {i}: {description}\n"
            f"- Tokens: {_team_result_int(r.get('tokens_in'))} in / "
            f"{_team_result_int(r.get('tokens_out'))} out\n\n"
            f"{result_text}\n"
        )

    return "\n".join(parts)

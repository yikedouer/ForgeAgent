"""技能工具——LLM 工具接口与剧本之间的桥梁。

当 LLM 调用此工具时，触发剧本解析：
  * inline 模式 → 返回解析后的提示词文本供注入
  * fork 模式  → 生成委托引擎在隔离环境中执行
"""

from __future__ import annotations

from ..toolkit import tool
from ..skills import playbook


@tool(
    name="skill",
    description=(
        "Invoke a registered skill (playbook) by name. "
        "Skills are prompt templates loaded from .forgecc/skills/ directories. "
        "Use this when a task matches a known skill pattern."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to invoke",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments passed to the skill template",
            },
        },
        "required": ["skill_name"],
    },
    risk_level="write",
)
def skill(skill_name: str, args: str = "") -> str:
    if not isinstance(skill_name, str):
        return "INVALID SKILL: skill_name must be non-empty."
    if not isinstance(args, str):
        return "INVALID ARGS: args must be a string when provided."
    skill_name = skill_name.strip()
    if not skill_name:
        return "INVALID SKILL: skill_name must be non-empty."
    result = playbook.invoke(skill_name, args)
    if result is None:
        available = [p.name for p in playbook.discover()]
        hint = f" Available: {', '.join(available)}" if available else ""
        return f"No skill named '{skill_name}'.{hint}"

    if result["mode"] == "fork":
        # 委托给隔离的子 Agent
        from ..core.engine import Engine

        # 如果剧本指定了 allowed-tools 则限制工具
        # （子引擎共享完整目录；通过提示词层面指导模型进行过滤）
        fork_prompt = (
            f"[Skill: {skill_name}]\n\n"
            f"{result['prompt']}\n\n"
            f"User arguments: {args or '(none)'}"
        )
        if result.get("allowed_tools"):
            fork_prompt += f"\n\nYou may ONLY use these tools: {', '.join(result['allowed_tools'])}"

        return Engine.execute_sub_agent(
            "general",
            f"skill:{skill_name}",
            fork_prompt,
            allowed_tools=result.get("allowed_tools"),
        )

    # inline 模式——注入解析后的提示词
    return f"[Skill \"{skill_name}\" activated]\n\n{result['prompt']}"

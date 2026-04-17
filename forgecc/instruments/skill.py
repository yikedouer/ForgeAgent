"""Skill instrument — bridge between the LLM tool interface and playbooks.

When the LLM calls this instrument, it triggers playbook resolution:
  * inline mode → returns the resolved prompt text for injection
  * fork mode  → spawns a delegate engine to execute in isolation
"""

from __future__ import annotations

from ..toolkit import instrument
from ..skills import playbook


@instrument(
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
    result = playbook.invoke(skill_name, args)
    if result is None:
        available = [p.name for p in playbook.discover()]
        hint = f" Available: {', '.join(available)}" if available else ""
        return f"No skill named '{skill_name}'.{hint}"

    if result["mode"] == "fork":
        # delegate to an isolated sub-engine
        from ..core.engine import Engine

        sub = Engine.spawn_delegate()
        if sub is None:
            return "Fork unavailable — engine not initialised."

        # restrict tools if the playbook specifies allowed-tools
        # (the sub-engine shares the full catalog; filtering happens
        #  at the prompt level by instructing the model)
        fork_prompt = (
            f"[Skill: {skill_name}]\n\n"
            f"{result['prompt']}\n\n"
            f"User arguments: {args or '(none)'}"
        )
        if result.get("allowed_tools"):
            fork_prompt += f"\n\nYou may ONLY use these instruments: {', '.join(result['allowed_tools'])}"

        answer = sub.run(fork_prompt)
        return answer

    # inline mode — inject the resolved prompt
    return f"[Skill \"{skill_name}\" activated]\n\n{result['prompt']}"

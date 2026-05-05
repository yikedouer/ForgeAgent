"""子 Agent 工具——类型化 fork-return 模式。

替代简单的 ``delegate`` 工具，提供完整的 agent 工具，
支持类型化子 Agent（explore、plan、verification、general）
和用户自定义 Agent。每个子 Agent 在隔离的上下文中运行，
使用过滤后的工具集，其最终文本响应返回给父对话。
"""

from __future__ import annotations

from ..toolkit import instrument

_VALID_AGENT_TYPES = {"explore", "plan", "verification", "general"}


@instrument(
    name="agent",
    description=(
        "Spawn a sub-agent to handle an isolated task. Choose a type: "
        "'explore' for fast read-only codebase search, "
        "'plan' for read-only analysis with structured plans, "
        "'verification' for running tests/linters to verify changes, "
        "'general' for full tool access (default). "
        "The sub-agent operates in a separate context window and "
        "returns its final response."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short 3-5 word task description (shown in UI)",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed, self-contained task instructions for the "
                    "sub-agent. Include all necessary context — the "
                    "sub-agent cannot see the parent conversation."
                ),
            },
            "type": {
                "type": "string",
                "enum": ["explore", "plan", "verification", "general"],
                "description": (
                    "Sub-agent type. Defaults to 'general' if omitted."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Override the model for this sub-agent. "
                    "If omitted, inherits the parent agent's model. "
                    "Example: use 'qwen3.5-flash' for simple tasks "
                    "while the parent uses 'qwen3.6-plus'."
                ),
            },
        },
        "required": ["description", "prompt"],
    },
    risk_level="write",
)
def agent(description: str, prompt: str, type: str = "general",
          model: str | None = None) -> str:
    if not isinstance(description, str) or not description.strip():
        return "INVALID DESCRIPTION: description must be non-empty."
    if not isinstance(prompt, str) or not prompt.strip():
        return "INVALID PROMPT: prompt must be non-empty."
    description = description.strip()
    prompt = prompt.strip()
    if not isinstance(type, str):
        allowed = ", ".join(sorted(_VALID_AGENT_TYPES))
        return f"INVALID TYPE: type must be one of: {allowed}."
    type = type.strip()
    if type not in _VALID_AGENT_TYPES:
        allowed = ", ".join(sorted(_VALID_AGENT_TYPES))
        return f"INVALID TYPE: type must be one of: {allowed}."
    if model is not None:
        if not isinstance(model, str):
            return "INVALID MODEL: model must be a string when provided."
        if not model.strip():
            model = None
        else:
            model = model.strip()

    # 延迟导入以打破循环依赖
    from ..core.engine import Engine

    return Engine.execute_sub_agent(type, description, prompt, model=model)

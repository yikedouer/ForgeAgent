"""Sub-agent delegation instrument.

When the primary engine encounters a task that benefits from a
separate context window (e.g. an isolated investigation), it can
delegate to a lightweight sub-engine. The sub-engine gets its own
message history but shares the same provider and instrument catalog.

This mirrors the fork-and-return pattern: the sub-agent runs to
completion, then its final text answer is returned as the
instrument result to the parent conversation.
"""

from __future__ import annotations

from ..toolkit import instrument

# The actual engine import is deferred to avoid circular deps.
# At call time we import lazily.

_DELEGATE_BUDGET = 30  # max rounds for a delegated task


@instrument(
    name="delegate",
    description=(
        "Spawn a sub-agent to handle an isolated task. The sub-agent has "
        "access to the same tools but operates in a separate context window. "
        "Returns the sub-agent's final response."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear, self-contained task description for the sub-agent",
            },
        },
        "required": ["task"],
    },
    risk_level="write",
)
def delegate(task: str) -> str:
    # lazy import to break circular dependency (engine → toolkit → delegate → engine)
    from ..core.engine import Engine

    sub = Engine.spawn_delegate()
    if sub is None:
        return "Delegation unavailable — engine not initialised."

    answer = sub.run(task)
    return answer

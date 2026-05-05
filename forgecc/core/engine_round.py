"""Engine per-round input preparation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..context.compaction import maybe_compact
from .engine_prompt import build_directive_text, build_wire_messages, select_tool_schemas


@dataclass(frozen=True)
class RoundInputs:
    directive: str
    wire_messages: list[dict]
    tool_schemas: list[dict]


def prepare_round_inputs(
    state: Any,
    *,
    plan_prompt_builder: Callable[..., str],
    plan_tool_defs: list[dict],
    toolkit_schemas: list[dict],
    memory_injector: Callable[[list[dict]], list[dict]],
    maybe_compact_fn: Callable[..., object] = maybe_compact,
    directive_builder: Callable[..., str] = build_directive_text,
    wire_builder: Callable[..., list[dict]] = build_wire_messages,
    schema_selector: Callable[..., list[dict]] = select_tool_schemas,
) -> RoundInputs:
    """Run compaction and build LLM wire messages and tool schemas."""
    compact_result = maybe_compact_fn(
        state.transcript,
        state.settings.context_budget,
        state.provider,
        session_id=state.session_id,
        collapse_state=state._collapse,
        failure_count=state._autocompact_failures,
        last_input_tokens=state._last_input_tokens,
        last_api_call_time=state._last_api_call_time,
    )
    if compact_result.collapse is not None:
        state._collapse = compact_result.collapse

    directive = directive_builder(
        settings=state.settings,
        custom_system_prompt=state._custom_system_prompt,
        plan_file_path=state._plan_file_path,
        plan_prompt_builder=plan_prompt_builder,
    )
    wire_messages = wire_builder(
        directive=directive,
        transcript=state.transcript,
        collapse=state._collapse,
    )
    wire_messages = memory_injector(wire_messages)
    tool_schemas = schema_selector(
        toolkit_schemas,
        custom_tool_names=state._custom_tool_names,
        plan_tool_defs=plan_tool_defs,
    )
    return RoundInputs(
        directive=directive,
        wire_messages=wire_messages,
        tool_schemas=tool_schemas,
    )

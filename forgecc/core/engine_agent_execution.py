"""Sub-agent execution orchestration helpers."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .engine_agent_record import begin_agent_run_record, finish_agent_run_record
from .engine_subagent import build_sub_agent_runtime
from .permissions import PermissionMode
from .settings import Settings
from .subagent_tools import resolve_sub_agent_tool_names


@dataclass(frozen=True)
class SubAgentExecutionResult:
    agent_id: str
    description: str
    result: str
    tokens_in: int
    tokens_out: int
    error: str | None
    model: str
    uses_parent_provider: bool


def _agent_id() -> str:
    return f"{time.time_ns()}"


def run_configured_sub_agent(
    *,
    engine_cls: type,
    parent_settings: Settings,
    parent_provider: object,
    parent_permission_mode: PermissionMode,
    workspace: str,
    agent_type: str,
    description: str,
    prompt: str,
    model: str | None,
    allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
    available_tool_names: Iterable[str],
    provider_factory: Callable[[Settings], object],
    config_lookup: Callable[[str], dict],
    agent_id_factory: Callable[[], str] = _agent_id,
    begin_record: Callable[..., object] = begin_agent_run_record,
    finish_record: Callable[..., object] = finish_agent_run_record,
    warn: Callable[..., object] | None = None,
) -> SubAgentExecutionResult:
    """Build, run, and record one configured sub-agent."""
    config = config_lookup(agent_type)
    agent_id = agent_id_factory()
    runtime = build_sub_agent_runtime(
        parent_settings=parent_settings,
        parent_provider=parent_provider,
        parent_permission_mode=parent_permission_mode,
        model=model,
        provider_factory=provider_factory,
    )
    record_kwargs: dict[str, Any] = {
        "workspace": workspace,
        "agent_id": agent_id,
        "description": description,
        "subagent_type": agent_type,
        "model": runtime.model,
        "prompt": prompt,
    }
    if warn is not None:
        record_kwargs["warn"] = warn
    record = begin_record(**record_kwargs)

    tool_names = resolve_sub_agent_tool_names(
        available_tool_names,
        config.get("tool_names"),
        allowed_tools,
    )
    sub = engine_cls(
        settings=runtime.settings,
        provider=runtime.provider,
        is_sub_agent=True,
        custom_system_prompt=config["system_prompt"],
        custom_tool_names=tool_names,
    )

    result_text = ""
    error_msg = None
    try:
        result_text = sub.run(prompt) or ""
    except Exception as exc:
        error_msg = str(exc)
        result_text = f"(Sub-agent failed: {exc})"

    finish_kwargs: dict[str, Any] = {
        "result": result_text or "(no output)",
        "tokens_in": sub._total_input_tokens,
        "tokens_out": sub._total_output_tokens,
        "error": error_msg,
    }
    if warn is not None:
        finish_kwargs["warn"] = warn
    finish_record(record, **finish_kwargs)

    return SubAgentExecutionResult(
        agent_id=agent_id,
        description=description,
        result=result_text,
        tokens_in=sub._total_input_tokens,
        tokens_out=sub._total_output_tokens,
        error=error_msg,
        model=runtime.model,
        uses_parent_provider=runtime.uses_parent_provider,
    )

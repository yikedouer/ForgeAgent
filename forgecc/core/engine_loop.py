"""Engine prompt construction, LLM recovery, accounting, and turn loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import toolkit
from ..context.collapse import project_view
from ..context.compaction import _prune, maybe_compact
from ..context.tool_storage import persist_if_large
from .errors import ContextWindowError
from .engine_session import maybe_start_memory_prefetch
from .engine_tools import (
    append_plan_tool_results,
    build_tool_calls,
    execute_normal_tool_calls,
    notify_instrument_callbacks,
    split_plan_tool_calls,
)
from .log import get_logger
from .permissions import PermissionMode
from .plan_mode import PLAN_TOOL_DEFS, PLAN_TOOL_NAMES, build_plan_mode_prompt


DirectiveBuilder = Callable[..., str]
PlanPromptBuilder = Callable[[str], str]
ProjectViewFn = Callable[[list[dict], object | None], list[dict]]
PruneFn = Callable[[list[dict], int], object]
log = get_logger(__name__)


@dataclass(frozen=True)
class RoundInputs:
    directive: str
    wire_messages: list[dict]
    tool_schemas: list[dict]


@dataclass(frozen=True)
class GenerateRecoveryResult:
    completion: object
    collapse_reset: bool = False


@dataclass(frozen=True)
class CompletionUsageReport:
    input_tokens: int
    output_tokens: int
    text_chars: int
    invocation_count: int


def build_directive_text(
    *,
    settings: object,
    custom_system_prompt: str | None,
    plan_file_path: str | None,
    plan_prompt_builder: PlanPromptBuilder = build_plan_mode_prompt,
    directive_builder: DirectiveBuilder | None = None,
) -> str:
    if custom_system_prompt:
        return custom_system_prompt
    if directive_builder is None:
        from ..interface.directive import build as directive_builder
    plan_prompt = plan_prompt_builder(plan_file_path) if plan_file_path else None
    return directive_builder(settings, plan_mode_prompt=plan_prompt)


def build_wire_messages(
    *,
    directive: str,
    transcript: list[dict],
    collapse: object | None,
    project: ProjectViewFn = project_view,
) -> list[dict]:
    return [{"role": "system", "content": directive}] + project(transcript, collapse)


def select_tool_schemas(
    all_schemas: list[dict],
    *,
    custom_tool_names: set[str] | None,
    plan_tool_defs: list[dict],
) -> list[dict]:
    if custom_tool_names is not None:
        return [
            schema for schema in all_schemas
            if schema["name"] in custom_tool_names
        ]
    return all_schemas + plan_tool_defs


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


def generate_with_context_recovery(
    *,
    provider: object,
    wire_messages: list[dict],
    tool_schemas: list[dict],
    on_token: Callable[[str], None] | None,
    directive: str,
    transcript: list[dict],
    prune: PruneFn = _prune,
) -> GenerateRecoveryResult:
    try:
        completion = provider.generate(
            messages=wire_messages,
            tool_schemas=tool_schemas,
            on_token=on_token,
        )
        return GenerateRecoveryResult(completion)
    except ContextWindowError:
        prune(transcript, 4)
        completion = provider.generate(
            messages=[{"role": "system", "content": directive}] + transcript,
            tool_schemas=tool_schemas,
            on_token=on_token,
        )
        return GenerateRecoveryResult(completion, collapse_reset=True)


def record_completion_usage(
    state: Any,
    completion: Any,
    *,
    now: float,
) -> CompletionUsageReport:
    """Update engine usage counters from a provider completion."""
    state._last_input_tokens = completion.usage_in
    state._last_api_call_time = now
    state._total_input_tokens += completion.usage_in
    state._total_output_tokens += completion.usage_out
    return CompletionUsageReport(
        input_tokens=completion.usage_in,
        output_tokens=completion.usage_out,
        text_chars=len(completion.text),
        invocation_count=len(completion.invocations),
    )


def run_agent_loop(
    state,
    *,
    user_input: str,
    on_token: Callable[[str], None] | None,
    on_instrument: Callable[[str, dict], None] | None,
) -> str:
    """Process one user message through the full Agent loop."""
    append_message = state._append_message
    append_message({"role": "user", "content": user_input})
    log.info("━" * 50)
    log.info("用户输入: %s", user_input[:200])

    state._pending_prefetch = maybe_start_memory_prefetch(
        is_sub_agent=state._is_sub_agent,
        user_input=user_input,
        workspace=state.settings.workspace,
        provider=state.provider,
        already_surfaced=state._already_surfaced,
        session_memory_bytes=state._session_memory_bytes,
    )

    for _ in range(state.settings.max_rounds):
        state._round += 1
        log.debug("── 第 %d 轮 ──", state._round)

        prepared = prepare_round_inputs(
            state,
            plan_prompt_builder=build_plan_mode_prompt,
            plan_tool_defs=PLAN_TOOL_DEFS,
            toolkit_schemas=toolkit.schemas(),
            memory_injector=state._inject_recalled_memories,
        )

        log.debug(
            "调用 LLM: %d 条消息, %d 个工具 schema",
            len(prepared.wire_messages),
            len(prepared.tool_schemas),
        )
        recovery = generate_with_context_recovery(
            provider=state.provider,
            wire_messages=prepared.wire_messages,
            tool_schemas=prepared.tool_schemas,
            on_token=on_token,
            directive=prepared.directive,
            transcript=state.transcript,
        )
        if recovery.collapse_reset:
            log.warning("ContextWindowError — 触发紧急裁剪后重试")
            state._collapse = None
        completion = recovery.completion

        usage = record_completion_usage(state, completion, now=time.time())
        log.info(
            "LLM 响应: in=%d out=%d  文本=%d字  工具调用=%d个",
            usage.input_tokens,
            usage.output_tokens,
            usage.text_chars,
            usage.invocation_count,
        )

        append_message(completion.raw_assistant_msg)

        if not completion.invocations:
            log.info("模型返回纯文本，本轮结束（共 %d 轮）", state._round)
            state._autosave_checkpoint()
            return completion.text

        all_calls = build_tool_calls(completion.invocations)
        notify_instrument_callbacks(
            completion.invocations,
            on_instrument,
            warn=log.warning,
        )

        plan_calls, normal_calls = split_plan_tool_calls(
            all_calls,
            plan_tool_names=PLAN_TOOL_NAMES,
        )

        append_plan_tool_results(
            plan_calls,
            execute_plan_tool=state._execute_plan_tool,
            append_message=append_message,
        )

        if state.enforcer.mode == PermissionMode.PLAN and state._plan_file_path:
            normal_calls = state._filter_plan_mode_calls(normal_calls)

        execute_normal_tool_calls(
            session_id=state.session_id,
            calls=normal_calls,
            run_batch=toolkit.run_batch,
            append_message=append_message,
            persist=persist_if_large,
            info=log.info,
            warn=log.warning,
        )

    log.warning("循环预算耗尽（%d 轮）", state.settings.max_rounds)
    state._autosave_checkpoint()
    return "(round budget exhausted — task may be incomplete)"

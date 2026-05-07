"""Engine prompt construction, LLM recovery, accounting, and turn loop."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .. import toolkit
from ..context.collapse import project_view
from ..context.compaction import _prune, maybe_compact
from ..context.tool_storage import persist_if_large
from .errors import ContextWindowError
from .engine_session import maybe_start_memory_prefetch
from .log import get_logger
from .permissions import PermissionMode
from .plan_mode import PLAN_TOOL_DEFS, PLAN_TOOL_NAMES, build_plan_mode_prompt


DirectiveBuilder = Callable[..., str]
PlanPromptBuilder = Callable[[str], str]
ProjectViewFn = Callable[[list[dict], object | None], list[dict]]
PruneFn = Callable[[list[dict], int], object]
ToolCall = tuple[str, object, object]
RunBatchFn = Callable[[list[ToolCall]], list[object]]
AppendMessageFn = Callable[[dict], object]
PersistResultFn = Callable[[str, str, str], str]
LogFn = Callable[..., object]
WarnFn = Callable[[str], None]
EventFn = Callable[[str, dict], None]
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


def build_tool_calls(invocations: Iterable[object]) -> list[ToolCall]:
    return [
        (inv.call_id, inv.fn_name, inv.fn_args)
        for inv in invocations
    ]


def split_plan_tool_calls(
    calls: list[ToolCall],
    *,
    plan_tool_names: set[str],
) -> tuple[list[ToolCall], list[ToolCall]]:
    plan_calls = [
        call for call in calls
        if isinstance(call[1], str) and call[1] in plan_tool_names
    ]
    normal_calls = [
        call for call in calls
        if not (isinstance(call[1], str) and call[1] in plan_tool_names)
    ]
    return plan_calls, normal_calls


def notify_tool_callbacks(
    invocations: Iterable[object],
    callback: Callable[[str, dict], None] | None,
    *,
    warn: WarnFn | None = None,
) -> None:
    if callback is None:
        return
    for inv in invocations:
        try:
            callback(inv.fn_name, inv.fn_args)
        except Exception as exc:
            if warn:
                warn(f"工具回调异常: {exc}")


def _tool_call_id(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _preview(text: object, limit: int = 240) -> str:
    value = str(text)
    if len(value) <= limit:
        return value
    return value[:limit - 3] + "..."


def emit_event(
    callback: EventFn | None,
    kind: str,
    payload: dict,
    *,
    warn: WarnFn | None = None,
) -> None:
    if callback is None:
        return
    try:
        callback(kind, payload)
    except Exception as exc:
        if warn:
            warn(f"事件回调异常: {exc}")


def append_plan_tool_results(
    calls: list[ToolCall],
    *,
    execute_plan_tool: Callable[[str], str],
    append_message: Callable[[dict], object],
    on_event: EventFn | None = None,
    warn: WarnFn | None = None,
) -> None:
    """Execute plan-mode tool calls and append their tool messages."""
    for idx, (call_id, fn_name, _args) in enumerate(calls):
        result_text = execute_plan_tool(str(fn_name))
        resolved_call_id = _tool_call_id(call_id, f"call_{idx}")
        append_message({
            "role": "tool",
            "tool_call_id": resolved_call_id,
            "content": result_text,
        })
        emit_event(
            on_event,
            "plan_tool_result",
            {
                "call_id": resolved_call_id,
                "name": str(fn_name),
                "output_chars": len(result_text),
                "preview": _preview(result_text),
            },
            warn=warn,
        )


def format_tool_call_log(call: tuple[object, object, object]) -> tuple[str, tuple[object, ...]]:
    _call_id, fn_name, args = call
    if isinstance(args, dict):
        args_preview = ", ".join(
            f"{key}={repr(value)[:80]}" for key, value in args.items()
        )
    else:
        args_preview = f"<invalid args: {type(args).__name__}>"
    return "工具调用: %s(%s)", (fn_name, args_preview)


def format_tool_result_log(result: object) -> tuple[str, tuple[object, ...]]:
    status = "✓" if result.ok else "✗"
    return "工具结果: %s %s → %d 字符", (
        status,
        result.name,
        len(result.output),
    )


def persist_tool_results(
    session_id: str,
    results: Iterable[object],
    *,
    persist: PersistResultFn = persist_if_large,
    warn: WarnFn | None = None,
) -> None:
    for result in results:
        try:
            result.output = persist(session_id, result.name, result.output)
        except Exception as exc:
            if warn:
                warn(f"工具结果持久化失败: {result.name} — {exc}")


def tool_result_messages(results: Iterable[object]) -> list[dict]:
    return [
        {
            "role": "tool",
            "tool_call_id": result.call_id,
            "content": result.output,
        }
        for result in results
    ]


def execute_normal_tool_calls(
    *,
    session_id: str,
    calls: list[ToolCall],
    run_batch: RunBatchFn,
    append_message: AppendMessageFn,
    persist: PersistResultFn = persist_if_large,
    info: LogFn | None = None,
    warn: Callable[[str], object] | None = None,
    on_event: EventFn | None = None,
) -> list[object]:
    """Run normal tool calls and feed persisted results back to transcript."""
    for call in calls:
        message, args = format_tool_call_log(call)
        if info is not None:
            info(message, *args)

    results = run_batch(calls)

    for result in results:
        message, args = format_tool_result_log(result)
        if info is not None:
            info(message, *args)
        emit_event(
            on_event,
            "tool_result",
            {
                "call_id": result.call_id,
                "name": result.name,
                "ok": result.ok,
                "output_chars": len(result.output),
                "preview": _preview(result.output),
            },
            warn=warn,
        )

    persist_tool_results(
        session_id,
        results,
        persist=persist,
        warn=warn,
    )
    for message in tool_result_messages(results):
        append_message(message)

    return results


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
        plan_file_path=state._plan.plan_file_path,
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
    on_tool: Callable[[str, dict], None] | None,
    on_event: EventFn | None = None,
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
        emit_event(
            on_event,
            "round_start",
            {"round": state._round},
            warn=log.warning,
        )
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
        emit_event(
            on_event,
            "llm_response",
            {
                "round": state._round,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "text_chars": usage.text_chars,
                "tool_calls": usage.invocation_count,
            },
            warn=log.warning,
        )
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
        notify_tool_callbacks(
            completion.invocations,
            on_tool,
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
            on_event=on_event,
            warn=log.warning,
        )

        if state.enforcer.mode == PermissionMode.PLAN and state._plan.plan_file_path:
            normal_calls = state._filter_plan_mode_calls(normal_calls)

        execute_normal_tool_calls(
            session_id=state.session_id,
            calls=normal_calls,
            run_batch=toolkit.run_batch,
            append_message=append_message,
            persist=persist_if_large,
            info=log.info,
            warn=log.warning,
            on_event=on_event,
        )

    log.warning("循环预算耗尽（%d 轮）", state.settings.max_rounds)
    state._autosave_checkpoint()
    return "(round budget exhausted — task may be incomplete)"

"""Engine turn loop orchestration."""

from __future__ import annotations

from typing import Callable

from .permissions import PermissionMode


def run_agent_loop(
    state,
    *,
    user_input: str,
    on_token: Callable[[str], None] | None,
    on_instrument: Callable[[str, dict], None] | None,
    append_message,
    autosave_checkpoint,
    maybe_start_memory_prefetch_fn,
    prepare_round_inputs_fn,
    generate_with_context_recovery_fn,
    record_completion_usage_fn,
    build_tool_calls_fn,
    notify_instrument_callbacks_fn,
    split_plan_tool_calls_fn,
    append_plan_tool_results_fn,
    execute_normal_tool_calls_fn,
    toolkit_schemas_fn,
    toolkit_run_batch_fn,
    persist_fn,
    memory_injector,
    plan_prompt_builder,
    plan_tool_defs,
    plan_tool_names,
    logger,
    now,
) -> str:
    """Process one user message through the full Agent loop."""
    append_message({"role": "user", "content": user_input})
    logger.info("━" * 50)
    logger.info("用户输入: %s", user_input[:200])

    state._pending_prefetch = maybe_start_memory_prefetch_fn(
        is_sub_agent=state._is_sub_agent,
        user_input=user_input,
        workspace=state.settings.workspace,
        provider=state.provider,
        already_surfaced=state._already_surfaced,
        session_memory_bytes=state._session_memory_bytes,
    )

    for _ in range(state.settings.max_rounds):
        state._round += 1
        logger.debug("── 第 %d 轮 ──", state._round)

        prepared = prepare_round_inputs_fn(
            state,
            plan_prompt_builder=plan_prompt_builder,
            plan_tool_defs=plan_tool_defs,
            toolkit_schemas=toolkit_schemas_fn(),
            memory_injector=memory_injector,
        )

        logger.debug(
            "调用 LLM: %d 条消息, %d 个工具 schema",
            len(prepared.wire_messages),
            len(prepared.tool_schemas),
        )
        recovery = generate_with_context_recovery_fn(
            provider=state.provider,
            wire_messages=prepared.wire_messages,
            tool_schemas=prepared.tool_schemas,
            on_token=on_token,
            directive=prepared.directive,
            transcript=state.transcript,
        )
        if recovery.collapse_reset:
            logger.warning("ContextWindowError — 触发紧急裁剪后重试")
            state._collapse = None
        completion = recovery.completion

        usage = record_completion_usage_fn(state, completion, now=now())
        logger.info(
            "LLM 响应: in=%d out=%d  文本=%d字  工具调用=%d个",
            usage.input_tokens,
            usage.output_tokens,
            usage.text_chars,
            usage.invocation_count,
        )

        append_message(completion.raw_assistant_msg)

        if not completion.invocations:
            logger.info("模型返回纯文本，本轮结束（共 %d 轮）", state._round)
            autosave_checkpoint()
            return completion.text

        all_calls = build_tool_calls_fn(completion.invocations)
        notify_instrument_callbacks_fn(
            completion.invocations,
            on_instrument,
            warn=logger.warning,
        )

        plan_calls, normal_calls = split_plan_tool_calls_fn(
            all_calls,
            plan_tool_names=plan_tool_names,
        )

        append_plan_tool_results_fn(
            plan_calls,
            execute_plan_tool=state._execute_plan_tool,
            append_message=append_message,
        )

        if state.enforcer.mode == PermissionMode.PLAN and state._plan_file_path:
            normal_calls = state._filter_plan_mode_calls(normal_calls)

        execute_normal_tool_calls_fn(
            session_id=state.session_id,
            calls=normal_calls,
            run_batch=toolkit_run_batch_fn,
            append_message=append_message,
            persist=persist_fn,
            info=logger.info,
            warn=logger.warning,
        )

    logger.warning("循环预算耗尽（%d 轮）", state.settings.max_rounds)
    autosave_checkpoint()
    return "(round budget exhausted — task may be incomplete)"

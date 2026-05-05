"""Engine sub-agent runtime, execution records, team execution, and API entries."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_store import create_agent_run, finalize_agent_run
from .permissions import PermissionMode
from .settings import Settings
from .subagent_tools import resolve_sub_agent_tool_names


ProviderFactory = Callable[[Settings], object]
CreateAgentRunFn = Callable[..., tuple[Path, Path]]
FinalizeAgentRunFn = Callable[..., None]
WarnFn = Callable[[str], None]
RunOneFn = Callable[..., dict]


@dataclass(frozen=True)
class SubAgentRuntime:
    settings: Settings
    provider: object
    model: str
    uses_parent_provider: bool


@dataclass(frozen=True)
class AgentRunRecord:
    md_path: Path
    json_path: Path


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


def build_sub_agent_runtime(
    *,
    parent_settings: Settings,
    parent_provider: object,
    parent_permission_mode: PermissionMode,
    model: str | None,
    provider_factory: ProviderFactory,
    max_rounds: int = 30,
) -> SubAgentRuntime:
    use_model = model or parent_settings.model
    sub_settings = parent_settings.replace(max_rounds=max_rounds)
    sub_provider = parent_provider
    uses_parent_provider = True

    if model and model != parent_settings.model:
        sub_settings = sub_settings.for_model(model)
        sub_provider = provider_factory(sub_settings)
        uses_parent_provider = False

    if parent_permission_mode == PermissionMode.PLAN:
        sub_settings = sub_settings.replace(permission_mode="plan")

    return SubAgentRuntime(
        settings=sub_settings,
        provider=sub_provider,
        model=use_model,
        uses_parent_provider=uses_parent_provider,
    )


def begin_agent_run_record(
    *,
    workspace: str,
    agent_id: str,
    description: str,
    subagent_type: str,
    model: str,
    prompt: str,
    create: CreateAgentRunFn = create_agent_run,
    warn: WarnFn | None = None,
) -> AgentRunRecord | None:
    try:
        md_path, json_path = create(
            workspace=workspace,
            agent_id=agent_id,
            name=description.replace(" ", "-").lower()[:40],
            description=description,
            subagent_type=subagent_type,
            model=model,
            prompt=prompt,
        )
    except Exception as exc:
        if warn:
            warn(f"创建子 Agent 运行记录失败: {exc}")
        return None
    return AgentRunRecord(md_path, json_path)


def finish_agent_run_record(
    record: AgentRunRecord | None,
    *,
    result: str,
    tokens_in: int,
    tokens_out: int,
    error: str | None,
    finalize: FinalizeAgentRunFn = finalize_agent_run,
    warn: WarnFn | None = None,
) -> None:
    if record is None:
        return
    try:
        finalize(
            record.md_path,
            record.json_path,
            result=result or "(no output)",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
        )
    except Exception as exc:
        if warn:
            warn(f"更新子 Agent 运行记录失败: {exc}")


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


def spec_description(spec: object) -> str:
    if isinstance(spec, dict) and isinstance(spec.get("description"), str):
        return spec["description"]
    return ""


def collect_team_results(
    agent_specs: list[dict],
    future_map: dict[object, int],
    *,
    completed_futures: Iterable[object] | None = None,
) -> list[dict]:
    ordered: list[dict | None] = [None] * len(agent_specs)
    futures = completed_futures if completed_futures is not None else as_completed(future_map)
    for future in futures:
        idx = future_map[future]
        try:
            ordered[idx] = future.result()
        except Exception as exc:
            ordered[idx] = {
                "description": spec_description(agent_specs[idx]),
                "result": f"(thread error: {exc})",
                "tokens_in": 0,
                "tokens_out": 0,
            }
    return [result for result in ordered if result is not None]


def team_token_totals(results: list[dict]) -> tuple[int, int]:
    return (
        sum(result["tokens_in"] for result in results),
        sum(result["tokens_out"] for result in results),
    )


def run_sub_agent_team(
    agent_specs: list[dict],
    *,
    run_one: RunOneFn,
    max_workers: int = 4,
) -> list[dict]:
    """Run sub-agent specs in parallel and preserve original spec order."""
    if not agent_specs:
        return []

    def _run_spec(spec: dict) -> dict:
        return run_one(
            agent_type=spec.get("type", "general"),
            description=spec.get("description", "sub-agent"),
            prompt=spec.get("prompt", ""),
            model=spec.get("model"),
        )

    with ThreadPoolExecutor(
        max_workers=min(len(agent_specs), max_workers),
        thread_name_prefix="forgecc-agent",
    ) as pool:
        future_map = {
            pool.submit(_run_spec, spec): i
            for i, spec in enumerate(agent_specs)
        }
        return collect_team_results(agent_specs, future_map)


def execute_sub_agent_entry(
    *,
    engine_cls,
    parent,
    agent_type: str,
    description: str,
    prompt: str,
    model: str | None,
    allowed_tools,
    run_configured_sub_agent_fn,
    provider_factory,
    toolkit_catalog_fn,
    config_lookup,
    logger,
) -> str:
    """Run one configured sub-agent and roll its token usage into parent."""
    if parent is None:
        return "Agent unavailable — engine not initialised."

    logger.info("═" * 40)
    execution = run_configured_sub_agent_fn(
        engine_cls=engine_cls,
        parent_settings=parent.settings,
        parent_provider=parent.provider,
        parent_permission_mode=parent.enforcer.mode,
        workspace=parent.settings.workspace,
        agent_type=agent_type,
        description=description,
        prompt=prompt,
        model=model,
        allowed_tools=allowed_tools,
        available_tool_names=(s.name for s in toolkit_catalog_fn().values()),
        provider_factory=provider_factory,
        config_lookup=config_lookup,
        warn=logger.warning,
    )

    if not execution.uses_parent_provider:
        logger.info("子 Agent 使用独立模型: %s", execution.model)

    parent._total_input_tokens += execution.tokens_in
    parent._total_output_tokens += execution.tokens_out
    logger.info(
        "子 Agent 完成: type=%s  输入 tokens=%d  输出=%d",
        agent_type,
        execution.tokens_in,
        execution.tokens_out,
    )
    logger.info("═" * 40)

    return execution.result or "(Sub-agent produced no output)"


def execute_sub_agents_parallel_entry(
    *,
    engine_cls,
    parent,
    agent_specs: list[dict],
    run_configured_sub_agent_fn,
    run_sub_agent_team_fn: Callable,
    provider_factory,
    toolkit_catalog_fn,
    config_lookup,
    logger,
) -> list[dict]:
    """Run a team of sub-agents in parallel and aggregate token usage."""
    if parent is None:
        return [
            {
                "description": spec_description(s),
                "result": "Agent unavailable — engine not initialised.",
                "tokens_in": 0,
                "tokens_out": 0,
            }
            for s in agent_specs
        ]

    if not agent_specs:
        return []

    def _run_one(
        *,
        agent_type: str,
        description: str,
        prompt: str,
        model: str | None,
    ) -> dict:
        execution = run_configured_sub_agent_fn(
            engine_cls=engine_cls,
            parent_settings=parent.settings,
            parent_provider=parent.provider,
            parent_permission_mode=parent.enforcer.mode,
            workspace=parent.settings.workspace,
            agent_type=agent_type,
            description=description,
            prompt=prompt,
            model=model,
            available_tool_names=(s.name for s in toolkit_catalog_fn().values()),
            provider_factory=provider_factory,
            config_lookup=config_lookup,
        )
        return {
            "description": execution.description,
            "result": execution.result or "(no output)",
            "tokens_in": execution.tokens_in,
            "tokens_out": execution.tokens_out,
        }

    logger.info("Team: 并行启动 %d 个子 Agent", len(agent_specs))

    results = run_sub_agent_team_fn(agent_specs, run_one=_run_one)

    total_in, total_out = team_token_totals(results)
    parent._total_input_tokens += total_in
    parent._total_output_tokens += total_out
    logger.info(
        "Team 完成: %d 个子 Agent  总 tokens=%d/%d",
        len(results),
        total_in,
        total_out,
    )
    return results

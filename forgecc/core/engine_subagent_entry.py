"""Public Engine classmethod helpers for sub-agent execution."""

from __future__ import annotations

from collections.abc import Callable

from .engine_team import spec_description, team_token_totals


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

"""Engine runtime component initialization."""

from __future__ import annotations


def initialize_engine_runtime(
    state,
    *,
    settings,
    is_sub_agent: bool,
    toolkit_module,
    checkpoint_module,
    mcp_manager_cls,
    mcp_transport_factory,
    mcp_client_factory,
    runtime_recorder_cls,
    permission_mode_cls,
    permission_enforcer_cls,
    plan_controller_cls,
    logger,
) -> None:
    """Attach runtime collaborators created during Engine initialization."""
    state._mcp_manager = mcp_manager_cls(
        settings.mcp_servers,
        register_mcp_tools=toolkit_module.register_mcp_tools,
        transport_factory=mcp_transport_factory,
        client_factory=mcp_client_factory,
        logger=logger,
    )
    state._mcp_transports = state._mcp_manager.transports
    state._runtime = runtime_recorder_cls(
        session_id=lambda: state.session_id,
        is_sub_agent=is_sub_agent,
        append_message_event=lambda session_id, index, message: checkpoint_module.append_message_event(
            session_id,
            index,
            message,
        ),
        logger=logger,
    )

    mode = permission_mode_cls(settings.permission_mode)
    state.enforcer = permission_enforcer_cls(mode, settings.workspace)
    toolkit_module.set_enforcer(state.enforcer)
    state._plan = plan_controller_cls(
        session_id=lambda: state.session_id,
        enforcer=state.enforcer,
        transcript=state.transcript,
        lookup_tool=toolkit_module.lookup,
    )


def start_configured_runtime(state, *, load_hook_file_fn, logger) -> None:
    """Load configured hooks, then start MCP servers."""
    for path in state.settings.hook_paths:
        try:
            load_hook_file_fn(path)
        except Exception as exc:
            logger.warning("加载 hook 文件失败: %s — %s", path, exc)
    state._mcp_manager.start()

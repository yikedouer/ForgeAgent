"""Engine lifecycle, session state, memory injection, compaction, and checkpoint API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import toolkit
from ..context import checkpoint as ckpt
from ..context.collapse import CollapseState
from ..context.compaction import CompactionResult, _conversation_tokens, maybe_compact
from ..context.tool_storage import reset_persisted_tracking as _reset_persisted_tracking
from ..memory.prefetch import MemoryPrefetch, start_memory_prefetch
from ..memory.recall import format_memories_for_injection
from .hooks import load_hook_file
from .log import get_logger
from .mcp import MCPClient, MCPServerManager, StdioMCPTransport
from .permissions import PermissionEnforcer, PermissionMode
from .plan_mode import PlanApprovalFn, PlanModeController
from .runtime import RuntimeRecorder
from .settings import Settings


FormatMemoriesFn = Callable[[list[object]], str]
StartPrefetchFn = Callable[[str, str, object, set[str], int], MemoryPrefetch]
SaveCheckpointFn = Callable[[ckpt.Checkpoint], Path]
LoadCheckpointFn = Callable[[str], ckpt.Checkpoint]
log = get_logger(__name__)


@dataclass(frozen=True)
class MemoryInjectionResult:
    messages: list[dict]
    consumed: bool
    surfaced_paths: tuple[str, ...] = ()
    additional_memory_bytes: int = 0


@dataclass(frozen=True)
class ManualCompactionReport:
    result: CompactionResult
    before_messages: int
    after_messages: int
    before_tokens: int
    after_tokens: int
    context_budget: int


@dataclass(frozen=True)
class RestoredCheckpoint:
    checkpoint: ckpt.Checkpoint
    should_switch_model: bool


class EnginePlanApiMixin:
    """Public plan-mode methods exposed on Engine."""

    def set_plan_approval_fn(self, fn: PlanApprovalFn) -> None:
        """Inject the interactive plan approval callback."""
        self._plan.set_approval_fn(fn)

    def toggle_plan_mode(self) -> str:
        """Toggle plan mode and return the active permission mode name."""
        mode = self._plan.toggle()
        if mode == "plan":
            self._log.info("进入计划模式  plan_file=%s", self._plan.plan_file_path)
        else:
            self._log.info("退出计划模式 → %s", mode)
        return mode

    def _execute_plan_tool(self, name: str) -> str:
        """Handle enter_plan_mode / exit_plan_mode tool calls."""
        result = self._plan.execute_tool(name)
        if self._plan.context_cleared:
            self._collapse = None
        return result

    def _handle_approval(self, result: dict, plan_content: str) -> str:
        """Handle approval callback output."""
        output = self._plan.handle_approval(result, plan_content)
        if self._plan.context_cleared:
            self._collapse = None
        return output

    def _filter_plan_mode_calls(
        self, calls: list[tuple[str, str, object]]
    ) -> list[tuple[str, str, object]]:
        """Return calls allowed by plan mode, appending denials to transcript."""
        return self._plan.filter_calls(calls)


class EngineCheckpointApiMixin:
    """Checkpoint persistence helpers exposed on Engine."""

    def switch_model(self, model: str) -> Settings:
        """Switch this engine to a new model and rebuild its provider."""
        self.settings = self.settings.for_model(model)
        self.provider = self._provider_factory(self.settings)
        return self.settings

    def save_checkpoint(self) -> str:
        """Persist the current transcript to disk."""
        return save_engine_checkpoint(
            session_id=self.session_id,
            messages=self.transcript,
            model=self.settings.model,
            tokens_in=self._total_input_tokens,
            tokens_out=self._total_output_tokens,
        )

    def restore_checkpoint(self, session_id: str, *, restore_model: bool = True) -> None:
        """Load a previously saved conversation."""
        restored = restore_engine_checkpoint(
            session_id,
            current_model=self.settings.model,
            restore_model=restore_model,
        )
        checkpoint = restored.checkpoint
        self.transcript = checkpoint.messages
        self.session_id = checkpoint.session_id
        self._total_input_tokens = checkpoint.tokens_in
        self._total_output_tokens = checkpoint.tokens_out
        if restored.should_switch_model:
            self.switch_model(checkpoint.model)


def initialize_engine_runtime(
    state,
    *,
    settings,
    is_sub_agent: bool,
) -> None:
    """Attach runtime collaborators created during Engine initialization."""
    state._mcp_manager = MCPServerManager(
        settings.mcp_servers,
        register_mcp_tools=toolkit.register_mcp_tools,
        transport_factory=StdioMCPTransport,
        client_factory=MCPClient,
        logger=log,
    )
    state._mcp_transports = state._mcp_manager.transports
    state._runtime = RuntimeRecorder(
        session_id=lambda: state.session_id,
        is_sub_agent=is_sub_agent,
        append_message_event=lambda session_id, index, message: ckpt.append_message_event(
            session_id,
            index,
            message,
        ),
        logger=log,
    )

    mode = PermissionMode(settings.permission_mode)
    state.enforcer = PermissionEnforcer(mode, settings.workspace)
    toolkit.set_enforcer(state.enforcer)
    state._plan = PlanModeController(
        session_id=lambda: state.session_id,
        enforcer=state.enforcer,
        transcript=state.transcript,
        lookup_tool=toolkit.lookup,
    )


def start_configured_runtime(state) -> None:
    """Load configured hooks, then start MCP servers."""
    for path in state.settings.hook_paths:
        try:
            load_hook_file(path)
        except Exception as exc:
            log.warning("加载 hook 文件失败: %s — %s", path, exc)
    state._mcp_manager.start()


def maybe_start_memory_prefetch(
    *,
    is_sub_agent: bool,
    user_input: str,
    workspace: str,
    provider: object,
    already_surfaced: set[str],
    session_memory_bytes: int,
    start_prefetch: StartPrefetchFn = start_memory_prefetch,
) -> MemoryPrefetch | None:
    """Start asynchronous memory prefetch for main agents only."""
    if is_sub_agent:
        return None
    return start_prefetch(
        user_input,
        workspace,
        provider,
        already_surfaced,
        session_memory_bytes,
    )


def inject_recalled_memories(
    wire_messages: list[dict],
    prefetch: object | None,
    *,
    format_memories: FormatMemoriesFn = format_memories_for_injection,
) -> MemoryInjectionResult:
    if (
        prefetch is None
        or getattr(prefetch, "consumed", False)
        or not getattr(prefetch, "settled", False)
    ):
        return MemoryInjectionResult(wire_messages, consumed=False)

    prefetch.consumed = True
    try:
        memories = prefetch.future.result(timeout=0)
    except Exception:
        return MemoryInjectionResult(wire_messages, consumed=True)

    if not memories:
        return MemoryInjectionResult(wire_messages, consumed=True)

    valid_memories = [
        m for m in memories
        if isinstance(getattr(m, "path", None), str)
        and isinstance(getattr(m, "content", None), str)
    ]
    if not valid_memories:
        return MemoryInjectionResult(wire_messages, consumed=True)

    injection = format_memories(valid_memories)
    surfaced_paths = tuple(m.path for m in valid_memories)
    additional_memory_bytes = sum(
        len(m.content.encode("utf-8")) for m in valid_memories
    )

    for i in range(len(wire_messages) - 1, -1, -1):
        if wire_messages[i].get("role") == "user":
            wire_messages[i]["content"] += "\n\n" + injection
            break
    else:
        wire_messages.insert(1, {"role": "user", "content": injection})

    return MemoryInjectionResult(
        wire_messages,
        consumed=True,
        surfaced_paths=surfaced_paths,
        additional_memory_bytes=additional_memory_bytes,
    )


def run_manual_compaction(
    messages: list[dict],
    *,
    budget: int,
    provider: object,
    session_id: str,
    collapse_state: CollapseState | None,
    failure_count: list[int],
    compact: Callable[..., CompactionResult] = maybe_compact,
) -> ManualCompactionReport:
    """Run manual compaction and return before/after statistics."""
    before_messages = len(messages)
    before_tokens = _conversation_tokens(messages)
    result = compact(
        messages,
        budget,
        provider,
        session_id=session_id,
        collapse_state=collapse_state,
        failure_count=failure_count,
    )
    return ManualCompactionReport(
        result=result,
        before_messages=before_messages,
        after_messages=len(messages),
        before_tokens=before_tokens,
        after_tokens=_conversation_tokens(messages),
        context_budget=budget,
    )


def reset_conversation_state(
    state,
    *,
    reset_persisted_tracking: Callable[[], object] = _reset_persisted_tracking,
) -> None:
    """Clear transcript and reset per-conversation runtime fields."""
    state.transcript.clear()
    state._round = 0
    state._collapse = None
    state._autocompact_failures[0] = 0
    state._last_input_tokens = 0
    state._last_api_call_time = None
    state._already_surfaced.clear()
    state._session_memory_bytes = 0
    state._pending_prefetch = None
    state._plan.context_cleared = False
    reset_persisted_tracking()


def save_engine_checkpoint(
    *,
    session_id: str,
    messages: list[dict],
    model: str,
    tokens_in: int,
    tokens_out: int,
    save: SaveCheckpointFn = ckpt.save,
) -> str:
    snapshot = ckpt.Checkpoint(
        session_id=session_id,
        messages=messages,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    return str(save(snapshot))


def restore_engine_checkpoint(
    session_id: str,
    *,
    current_model: str,
    restore_model: bool = True,
    load: LoadCheckpointFn = ckpt.load,
) -> RestoredCheckpoint:
    snapshot = load(session_id)
    return RestoredCheckpoint(
        checkpoint=snapshot,
        should_switch_model=bool(
            restore_model and snapshot.model and snapshot.model != current_model
        ),
    )

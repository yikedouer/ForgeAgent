"""Engine conversation state reset helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..context.tool_storage import reset_persisted_tracking as _reset_persisted_tracking


def reset_conversation_state(
    state: Any,
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
    state._context_cleared = False
    reset_persisted_tracking()

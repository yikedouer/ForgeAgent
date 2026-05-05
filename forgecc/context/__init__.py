"""上下文管理——四层压缩、折叠投影和会话持久化。"""

from .compaction import maybe_compact, CompactionResult
from .collapse import CollapseState, try_collapse, project_view
from .tool_storage import persist_large_result, load_persisted_result
from .checkpoint import (
    Checkpoint,
    append_message_event,
    save,
    load,
    load_events,
    list_checkpoints,
    latest_checkpoint,
)

__all__ = [
    "maybe_compact", "CompactionResult",
    "CollapseState", "try_collapse", "project_view",
    "persist_large_result", "load_persisted_result",
    "Checkpoint", "append_message_event", "save", "load", "load_events",
    "list_checkpoints", "latest_checkpoint",
]

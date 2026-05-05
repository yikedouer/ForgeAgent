"""Engine memory injection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..memory.recall import format_memories_for_injection
from ..memory.prefetch import MemoryPrefetch, start_memory_prefetch


FormatMemoriesFn = Callable[[list[object]], str]
StartPrefetchFn = Callable[[str, str, object, set[str], int], MemoryPrefetch]


@dataclass(frozen=True)
class MemoryInjectionResult:
    messages: list[dict]
    consumed: bool
    surfaced_paths: tuple[str, ...] = ()
    additional_memory_bytes: int = 0


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

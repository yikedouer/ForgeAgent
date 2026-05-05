from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass

from forgecc.core.engine_session import inject_recalled_memories, maybe_start_memory_prefetch


@dataclass
class Memory:
    path: str
    content: str


@dataclass
class Prefetch:
    consumed: bool
    settled: bool
    future: Future


def test_inject_recalled_memories_appends_to_last_user_message():
    future = Future()
    future.set_result([Memory(path="/mem/a.md", content="remember this")])
    prefetch = Prefetch(consumed=False, settled=True, future=future)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "latest"},
    ]

    result = inject_recalled_memories(messages, prefetch)

    assert result.messages[-1]["content"].startswith("latest\n\n")
    assert "remember this" in result.messages[-1]["content"]
    assert result.consumed is True
    assert result.surfaced_paths == ("/mem/a.md",)
    assert result.additional_memory_bytes == len("remember this".encode("utf-8"))


def test_inject_recalled_memories_ignores_malformed_prefetch_results():
    future = Future()
    future.set_result([{"path": "/mem/a.md", "content": "bad shape"}])
    prefetch = Prefetch(consumed=False, settled=True, future=future)
    messages = [{"role": "user", "content": "latest"}]

    result = inject_recalled_memories(messages, prefetch)

    assert result.messages == messages
    assert result.consumed is True
    assert result.surfaced_paths == ()
    assert result.additional_memory_bytes == 0


def test_inject_recalled_memories_leaves_unsettled_prefetch_untouched():
    future = Future()
    prefetch = Prefetch(consumed=False, settled=False, future=future)
    messages = [{"role": "user", "content": "latest"}]

    result = inject_recalled_memories(messages, prefetch)

    assert result.messages == messages
    assert result.consumed is False
    assert prefetch.consumed is False


def test_maybe_start_memory_prefetch_starts_for_main_agent():
    calls = []

    result = maybe_start_memory_prefetch(
        is_sub_agent=False,
        user_input="remember",
        workspace="/tmp/workspace",
        provider=object(),
        already_surfaced={"old.md"},
        session_memory_bytes=12,
        start_prefetch=lambda *args: calls.append(args) or "prefetch",
    )

    assert result == "prefetch"
    assert calls[0][0] == "remember"
    assert calls[0][1] == "/tmp/workspace"
    assert calls[0][3] == {"old.md"}
    assert calls[0][4] == 12


def test_maybe_start_memory_prefetch_skips_sub_agents():
    result = maybe_start_memory_prefetch(
        is_sub_agent=True,
        user_input="remember",
        workspace="/tmp/workspace",
        provider=object(),
        already_surfaced=set(),
        session_memory_bytes=0,
        start_prefetch=lambda *args: (_ for _ in ()).throw(AssertionError("unused")),
    )

    assert result is None

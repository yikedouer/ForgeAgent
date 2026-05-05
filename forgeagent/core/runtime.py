"""Runtime transcript event recording."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeRecorder:
    """Append transcript messages and mirror main-agent events to JSONL."""

    def __init__(
        self,
        *,
        session_id: Callable[[], str],
        is_sub_agent: bool,
        append_message_event: Callable[[str, int, dict], None],
        logger: Any | None = None,
    ):
        self.session_id = session_id
        self.is_sub_agent = is_sub_agent
        self.append_message_event = append_message_event
        self.logger = logger

    def append(self, transcript: list[dict], message: dict) -> None:
        transcript.append(message)
        if self.is_sub_agent:
            return
        try:
            self.append_message_event(
                self.session_id(),
                len(transcript) - 1,
                message,
            )
        except Exception as exc:
            self._warning("追加 runtime event 失败: %s", exc)

    def _warning(self, message: str, *args: object) -> None:
        warning = getattr(self.logger, "warning", None)
        if callable(warning):
            warning(message, *args)

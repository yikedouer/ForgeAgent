"""Engine — the conductor that orchestrates the think → act → observe loop.

The engine owns:
  * The conversation transcript (list of messages).
  * The provider (LLM connection).
  * The instrument catalog (via toolkit).
  * The compaction pipeline (via context.compaction).

Public API is deliberately small:
  engine.run(user_input) → str   # one user turn, may span many rounds
"""

from __future__ import annotations

import uuid
from typing import Callable

from .. import toolkit
from .providers import Provider
from .settings import Settings
from .permissions import PermissionMode, PermissionEnforcer
from .errors import ContextWindowError
from ..context.compaction import maybe_compact
from ..context import checkpoint as ckpt

# ensure instruments are registered on first import
from .. import instruments as _instruments  # noqa: F401


# ── Singleton reference for delegate spawning ───────────────

_active_engine: Engine | None = None


class Engine:
    """Core agent loop — think, act, observe, repeat."""

    def __init__(self, settings: Settings, provider: Provider):
        global _active_engine

        self.settings = settings
        self.provider = provider
        self.transcript: list[dict] = []
        self.session_id = uuid.uuid4().hex[:12]
        self._round = 0

        # set up permission enforcement
        mode = PermissionMode(settings.permission_mode)
        self.enforcer = PermissionEnforcer(mode, settings.workspace)
        toolkit.set_enforcer(self.enforcer)

        _active_engine = self

    # ── Public interface ────────────────────────────────────

    def run(
        self,
        user_input: str,
        on_token: Callable[[str], None] | None = None,
        on_instrument: Callable[[str, dict], None] | None = None,
    ) -> str:
        """Process one user message through the full agent loop.

        The loop continues until the model responds with plain text
        (no tool invocations) or the round budget is exhausted.
        """
        self.transcript.append({"role": "user", "content": user_input})

        for _ in range(self.settings.max_rounds):
            self._round += 1

            # compact if we're running hot
            maybe_compact(self.transcript, self.settings.context_budget, self.provider)

            # build messages: system + transcript
            from ..interface.directive import build as build_directive
            directive = build_directive(self.settings)
            wire_messages = [{"role": "system", "content": directive}] + self.transcript

            # call the LLM (with context-window auto-recovery)
            try:
                completion = self.provider.generate(
                    messages=wire_messages,
                    tool_schemas=toolkit.schemas(),
                    on_token=on_token,
                )
            except ContextWindowError:
                # emergency compact and retry once
                from ..context.compaction import _prune
                _prune(self.transcript, keep_recent=4)
                directive = build_directive(self.settings)
                wire_messages = [{"role": "system", "content": directive}] + self.transcript
                completion = self.provider.generate(
                    messages=wire_messages,
                    tool_schemas=toolkit.schemas(),
                    on_token=on_token,
                )

            # append the raw assistant message to transcript
            self.transcript.append(completion.raw_assistant_msg)

            # if no tool invocations → model is done, return text
            if not completion.invocations:
                return completion.text

            # execute requested instruments
            calls = [
                (inv.call_id, inv.fn_name, inv.fn_args)
                for inv in completion.invocations
            ]

            if on_instrument:
                for inv in completion.invocations:
                    on_instrument(inv.fn_name, inv.fn_args)

            results = toolkit.run_batch(calls)

            # feed results back into the transcript
            for r in results:
                self.transcript.append({
                    "role": "tool",
                    "tool_call_id": r.call_id,
                    "content": r.output,
                })

        return "(round budget exhausted — task may be incomplete)"

    def save_checkpoint(self) -> str:
        """Persist current conversation to disk."""
        c = ckpt.Checkpoint(
            session_id=self.session_id,
            messages=self.transcript,
            model=self.settings.model,
            tokens_in=self.provider.tokens_used[0],
            tokens_out=self.provider.tokens_used[1],
        )
        path = ckpt.save(c)
        return str(path)

    def restore_checkpoint(self, session_id: str) -> None:
        """Load a previous session's transcript."""
        c = ckpt.load(session_id)
        self.transcript = c.messages
        self.session_id = c.session_id

    # ── Delegate spawning ───────────────────────────────────

    @classmethod
    def spawn_delegate(cls) -> Engine | None:
        """Create a lightweight sub-engine that shares the same
        provider but has a fresh transcript. Used by the delegate
        instrument for isolated sub-tasks."""
        if _active_engine is None:
            return None

        sub_settings = _active_engine.settings.replace(
            max_rounds=30,  # tighter budget for sub-tasks
        )
        return cls(
            settings=sub_settings,
            provider=_active_engine.provider,
        )

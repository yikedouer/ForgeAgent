"""Engine-facing checkpoint and model switch API."""

from __future__ import annotations

from .settings import Settings
from .engine_checkpoint import restore_engine_checkpoint, save_engine_checkpoint


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

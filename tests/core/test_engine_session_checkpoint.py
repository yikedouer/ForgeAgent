from __future__ import annotations

from pathlib import Path

from forgecc.context import checkpoint as ckpt
from forgecc.core.engine_session import (
    save_engine_checkpoint,
    restore_engine_checkpoint,
)


def test_save_engine_checkpoint_builds_snapshot_from_engine_state():
    captured = {}

    def fake_save(snapshot: ckpt.Checkpoint) -> Path:
        captured["snapshot"] = snapshot
        return Path("/tmp/session.json")

    path = save_engine_checkpoint(
        session_id="session-a",
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        tokens_in=123,
        tokens_out=45,
        save=fake_save,
    )

    assert path == "/tmp/session.json"
    snapshot = captured["snapshot"]
    assert snapshot.session_id == "session-a"
    assert snapshot.messages == [{"role": "user", "content": "hello"}]
    assert snapshot.model == "test-model"
    assert snapshot.tokens_in == 123
    assert snapshot.tokens_out == 45


def test_restore_engine_checkpoint_flags_model_switch_when_checkpoint_differs():
    snapshot = ckpt.Checkpoint(
        session_id="session-a",
        messages=[],
        model="deepseek-chat",
        tokens_in=1,
        tokens_out=2,
    )

    restored = restore_engine_checkpoint(
        "session-a",
        current_model="qwen3.6-plus",
        load=lambda session_id: snapshot,
    )

    assert restored.checkpoint is snapshot
    assert restored.should_switch_model is True


def test_restore_engine_checkpoint_can_preserve_current_model():
    snapshot = ckpt.Checkpoint(
        session_id="session-a",
        messages=[],
        model="deepseek-chat",
    )

    restored = restore_engine_checkpoint(
        "session-a",
        current_model="qwen3.6-plus",
        restore_model=False,
        load=lambda session_id: snapshot,
    )

    assert restored.checkpoint is snapshot
    assert restored.should_switch_model is False

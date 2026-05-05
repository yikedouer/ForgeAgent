"""Engine checkpoint orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..context import checkpoint as ckpt


SaveCheckpointFn = Callable[[ckpt.Checkpoint], Path]
LoadCheckpointFn = Callable[[str], ckpt.Checkpoint]


@dataclass(frozen=True)
class RestoredCheckpoint:
    checkpoint: ckpt.Checkpoint
    should_switch_model: bool


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

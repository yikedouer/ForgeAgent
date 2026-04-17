"""Session checkpointing — save and restore conversation state.

Design: Each checkpoint is a JSON file containing the full message
history plus metadata. This keeps the format human-readable and easy
to inspect or migrate.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


_CHECKPOINT_DIR = Path.home() / ".forgecc" / "sessions"


@dataclass
class Checkpoint:
    session_id: str
    messages: list[dict]
    model: str = ""
    created_at: float = field(default_factory=time.time)
    tokens_in: int = 0
    tokens_out: int = 0


def save(ckpt: Checkpoint, directory: Path | None = None) -> Path:
    """Persist a checkpoint to disk. Returns the file path."""
    target = directory or _CHECKPOINT_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{ckpt.session_id}.json"
    path.write_text(
        json.dumps(asdict(ckpt), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def load(session_id: str, directory: Path | None = None) -> Checkpoint:
    """Load a previously saved checkpoint."""
    target = directory or _CHECKPOINT_DIR
    raw = json.loads((target / f"{session_id}.json").read_text(encoding="utf-8"))
    return Checkpoint(
        session_id=raw["session_id"],
        messages=raw["messages"],
        model=raw.get("model", ""),
        created_at=raw.get("created_at", 0),
        tokens_in=raw.get("tokens_in", 0),
        tokens_out=raw.get("tokens_out", 0),
    )


def list_checkpoints(directory: Path | None = None) -> list[str]:
    """Return session IDs of all saved checkpoints."""
    target = directory or _CHECKPOINT_DIR
    if not target.is_dir():
        return []
    return sorted(
        p.stem for p in target.glob("*.json")
    )

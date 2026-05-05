"""会话检查点——保存和恢复对话状态。

设计：每个检查点是一个 JSON 文件，包含完整的消息
历史和元数据。该格式可读性好，便于检查和迁移。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


_DEFAULT_CHECKPOINT_DIR = Path.home() / ".forgeagent" / "sessions"
MAX_SESSION_FILE_STEM_BYTES = 120


def session_dir() -> Path:
    """Return the base directory for session-scoped state."""
    return Path(os.environ.get("FORGEAGENT_SESSION_DIR", str(_DEFAULT_CHECKPOINT_DIR))).expanduser()


def validate_session_id(session_id: str) -> None:
    """拒绝会话 ID 中的路径分隔符和空值。"""
    if (
        not isinstance(session_id, str)
        or not session_id
        or not session_id.strip()
        or Path(session_id).name != session_id
        or "\\" in session_id
    ):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def _session_file_stem(session_id: str) -> str:
    """将 session_id 转成安全、稳定、不易碰撞的文件名 stem。"""
    if len(session_id.encode("utf-8")) <= MAX_SESSION_FILE_STEM_BYTES:
        return session_id
    suffix = "_" + hashlib.sha256(session_id.encode()).hexdigest()[:8]
    prefix_budget = MAX_SESSION_FILE_STEM_BYTES - len(suffix)
    prefix = session_id.encode("utf-8")[:prefix_budget].decode(
        "utf-8", errors="ignore"
    )
    return prefix + suffix


def session_file_stem(session_id: str) -> str:
    """校验并返回适合用作会话相关文件名的稳定 stem。"""
    validate_session_id(session_id)
    return _session_file_stem(session_id)


def _checkpoint_path(directory: Path, session_id: str) -> Path:
    """返回检查点文件路径，并拒绝路径穿越形式的 session_id。"""
    return directory / f"{session_file_stem(session_id)}.json"


def _events_path(directory: Path, session_id: str) -> Path:
    """返回 JSONL 会话事件流路径，与 checkpoint 快照并列保存。"""
    return directory / f"{session_file_stem(session_id)}.jsonl"


@dataclass
class Checkpoint:
    session_id: str
    messages: list[dict]
    model: str = ""
    created_at: float = field(default_factory=time.time)
    tokens_in: int = 0
    tokens_out: int = 0


def _token_count(raw: object, session_id: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    return raw


def _timestamp(raw: object, session_id: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    return raw


def _reject_json_constant(raw: str) -> None:
    raise ValueError(raw)


def _validate_json_value(raw: object, session_id: str) -> None:
    if isinstance(raw, dict):
        if any(not isinstance(key, str) for key in raw):
            raise ValueError(f"Invalid checkpoint: {session_id!r}")
        for value in raw.values():
            _validate_json_value(value, session_id)
    elif isinstance(raw, list):
        for value in raw:
            _validate_json_value(value, session_id)
    elif raw is None or isinstance(raw, (str, int, float, bool)):
        return
    else:
        raise ValueError(f"Invalid checkpoint: {session_id!r}")


def save(ckpt: Checkpoint, directory: Path | None = None) -> Path:
    """将检查点持久化到磁盘。返回文件路径。"""
    if (
        not isinstance(ckpt.messages, list)
        or any(not isinstance(message, dict) for message in ckpt.messages)
    ):
        raise ValueError(f"Invalid checkpoint: {ckpt.session_id!r}")
    if not isinstance(ckpt.model, str):
        raise ValueError(f"Invalid checkpoint: {ckpt.session_id!r}")
    _validate_json_value(ckpt.messages, ckpt.session_id)
    _timestamp(ckpt.created_at, ckpt.session_id)
    _token_count(ckpt.tokens_in, ckpt.session_id)
    _token_count(ckpt.tokens_out, ckpt.session_id)
    target = directory or session_dir()
    path = _checkpoint_path(target, ckpt.session_id)
    try:
        snapshot = json.dumps(
            asdict(ckpt),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        events = [
            {
                "type": "checkpoint",
                "session_id": ckpt.session_id,
                "model": ckpt.model,
                "created_at": ckpt.created_at,
                "tokens_in": ckpt.tokens_in,
                "tokens_out": ckpt.tokens_out,
            },
            *(
                {
                    "type": "message",
                    "session_id": ckpt.session_id,
                    "index": index,
                    "message": message,
                }
                for index, message in enumerate(ckpt.messages)
            ),
        ]
        event_stream = "\n".join(
            json.dumps(event, ensure_ascii=False, allow_nan=False)
            for event in events
        )
        if event_stream:
            event_stream += "\n"
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid checkpoint: {ckpt.session_id!r}") from exc
    target.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot, encoding="utf-8")
    _events_path(target, ckpt.session_id).write_text(event_stream, encoding="utf-8")
    return path


def append_message_event(
    session_id: str,
    index: int,
    message: dict,
    directory: Path | None = None,
) -> Path:
    """Append one message event to the session JSONL event stream."""
    validate_session_id(session_id)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError(f"Invalid checkpoint event index: {session_id!r}")
    if not isinstance(message, dict):
        raise ValueError(f"Invalid checkpoint event: {session_id!r}")
    _validate_json_value(message, session_id)
    target = directory or session_dir()
    path = _events_path(target, session_id)
    event = {
        "type": "message",
        "session_id": session_id,
        "index": index,
        "message": message,
    }
    try:
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid checkpoint event: {session_id!r}") from exc
    target.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def load(session_id: str, directory: Path | None = None) -> Checkpoint:
    """加载先前保存的检查点。"""
    target = directory or session_dir()
    path = _checkpoint_path(target, session_id)
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid checkpoint: {session_id!r}") from exc
    messages = raw.get("messages") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or not isinstance(messages, list):
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    if any(not isinstance(message, dict) for message in messages):
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    loaded_session_id = raw.get("session_id")
    if not isinstance(loaded_session_id, str) or loaded_session_id != session_id:
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    model = raw.get("model", "")
    if not isinstance(model, str):
        raise ValueError(f"Invalid checkpoint: {session_id!r}")
    return Checkpoint(
        session_id=loaded_session_id,
        messages=messages,
        model=model,
        created_at=_timestamp(raw.get("created_at", 0), session_id),
        tokens_in=_token_count(raw.get("tokens_in", 0), session_id),
        tokens_out=_token_count(raw.get("tokens_out", 0), session_id),
    )


def load_events(session_id: str, directory: Path | None = None) -> list[dict]:
    """加载会话 JSONL 事件流。"""
    target = directory or session_dir()
    path = _events_path(target, session_id)
    events: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            raw = json.loads(line, parse_constant=_reject_json_constant)
            if not isinstance(raw, dict):
                raise ValueError
            _validate_json_value(raw, session_id)
            events.append(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid checkpoint events: {session_id!r}") from exc
    return events


def list_checkpoints(directory: Path | None = None) -> list[str]:
    """返回所有已保存检查点的会话 ID。"""
    target = directory or session_dir()
    if not target.is_dir():
        return []
    session_ids: list[str] = []
    for p in target.glob("*.json"):
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            session_id = raw.get("session_id") if isinstance(raw, dict) else None
            if isinstance(session_id, str):
                validate_session_id(session_id)
                session_ids.append(session_id)
            else:
                session_ids.append(p.stem)
        except Exception:
            session_ids.append(p.stem)
    return sorted(session_ids)


def latest_checkpoint(directory: Path | None = None) -> str | None:
    """返回最近修改的检查点会话 ID；没有检查点时返回 None。"""
    target = directory or session_dir()
    if not target.is_dir():
        return None

    latest: tuple[float, str] | None = None
    for p in target.glob("*.json"):
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            session_id = raw.get("session_id") if isinstance(raw, dict) else None
            if isinstance(session_id, str):
                validate_session_id(session_id)
            else:
                session_id = p.stem
        except Exception:
            session_id = p.stem

        mtime = p.stat().st_mtime
        if latest is None or mtime > latest[0]:
            latest = (mtime, session_id)

    return None if latest is None else latest[1]

"""test_checkpoint.py — 会话持久化测试。"""

from __future__ import annotations

import json

import pytest

import forgeagent.context.checkpoint as ckpt
from forgeagent.context.checkpoint import Checkpoint, save, load, list_checkpoints


class TestSaveLoad:
    def test_save_uses_env_session_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGEAGENT_SESSION_DIR", str(tmp_path))
        ckpt = Checkpoint(session_id="env", messages=[{"role": "user", "content": "hi"}])

        path = save(ckpt)

        assert path == tmp_path / "env.json"
        assert path.exists()

    def test_env_session_dir_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGEAGENT_SESSION_DIR", "~/sessions")
        ckpt = Checkpoint(session_id="env", messages=[{"role": "user", "content": "hi"}])

        path = save(ckpt)

        assert path == home / "sessions" / "env.json"
        assert path.exists()

    def test_save_creates_file(self, tmp_path):
        ckpt = Checkpoint(session_id="s1", messages=[{"role": "user", "content": "hi"}])
        path = save(ckpt, directory=tmp_path)
        assert path.exists()
        assert path.name == "s1.json"

    def test_load_restores(self, tmp_path):
        ckpt = Checkpoint(
            session_id="s2",
            messages=[{"role": "user", "content": "hello"}],
            model="test-model",
            tokens_in=100,
            tokens_out=50,
        )
        save(ckpt, directory=tmp_path)
        loaded = load("s2", directory=tmp_path)
        assert loaded.session_id == "s2"
        assert loaded.messages == ckpt.messages
        assert loaded.model == "test-model"
        assert loaded.tokens_in == 100
        assert loaded.tokens_out == 50

    def test_roundtrip_consistency(self, tmp_path):
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        ckpt = Checkpoint(session_id="rt", messages=msgs, model="m")
        save(ckpt, directory=tmp_path)
        loaded = load("rt", directory=tmp_path)
        assert loaded.messages == msgs

    def test_save_writes_jsonl_event_stream(self, tmp_path):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        checkpoint = Checkpoint(
            session_id="events",
            messages=messages,
            model="m",
            tokens_in=10,
            tokens_out=5,
        )

        save(checkpoint, directory=tmp_path)

        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        assert events == [
            {
                "type": "checkpoint",
                "session_id": "events",
                "model": "m",
                "created_at": checkpoint.created_at,
                "tokens_in": 10,
                "tokens_out": 5,
            },
            {
                "type": "message",
                "session_id": "events",
                "index": 0,
                "message": messages[0],
            },
            {
                "type": "message",
                "session_id": "events",
                "index": 1,
                "message": messages[1],
            },
        ]

    def test_load_events_reads_jsonl_event_stream(self, tmp_path):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        checkpoint = Checkpoint(session_id="events", messages=messages, model="m")
        save(checkpoint, directory=tmp_path)

        events = ckpt.load_events("events", directory=tmp_path)

        assert events[0]["type"] == "checkpoint"
        assert events[0]["session_id"] == "events"
        assert events[1:] == [
            {
                "type": "message",
                "session_id": "events",
                "index": 0,
                "message": messages[0],
            },
            {
                "type": "message",
                "session_id": "events",
                "index": 1,
                "message": messages[1],
            },
        ]

    def test_overwrite(self, tmp_path):
        ckpt1 = Checkpoint(session_id="ow", messages=[{"role": "user", "content": "v1"}])
        save(ckpt1, directory=tmp_path)
        ckpt2 = Checkpoint(session_id="ow", messages=[{"role": "user", "content": "v2"}])
        save(ckpt2, directory=tmp_path)
        loaded = load("ow", directory=tmp_path)
        assert loaded.messages[0]["content"] == "v2"

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load("nonexistent", directory=tmp_path)

    def test_load_rejects_non_object_checkpoint(self, tmp_path):
        (tmp_path / "bad.json").write_text("[]", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_invalid_json_checkpoint(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_list_messages(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "bad", "messages": "not-list"}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_object_messages(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "bad", "messages": ["not-object"]}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_string_model(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "bad", "messages": [], "model": ["bad"]}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_boolean_token_counts(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps(
                {
                    "session_id": "bad",
                    "messages": [],
                    "tokens_in": True,
                    "tokens_out": False,
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_numeric_created_at(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "bad", "messages": [], "created_at": ["now"]}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_finite_created_at(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            '{"session_id": "bad", "messages": [], "created_at": NaN}',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_load_rejects_non_standard_json_constants(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            '{"session_id": "bad", "messages": [{"content": NaN}]}',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_save_rejects_boolean_token_counts(self, tmp_path):
        ckpt = Checkpoint(
            session_id="bad",
            messages=[],
            tokens_in=True,
            tokens_out=False,
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_string_model(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages=[], model=["bad"])

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_numeric_created_at(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages=[], created_at=["now"])

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_finite_created_at(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages=[], created_at=float("nan"))

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_list_messages(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages="not-list")

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_object_messages(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages=["not-object"])

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_string_message_keys(self, tmp_path):
        ckpt = Checkpoint(session_id="bad", messages=[{1: "assistant"}])

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_finite_message_values(self, tmp_path):
        ckpt = Checkpoint(
            session_id="bad",
            messages=[{"role": "assistant", "content": float("nan")}],
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_json_serializable_message_values(self, tmp_path):
        ckpt = Checkpoint(
            session_id="bad",
            messages=[{"role": "assistant", "content": object()}],
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_json_type_message_values(self, tmp_path):
        ckpt = Checkpoint(
            session_id="bad",
            messages=[{"role": "assistant", "content": ("a", "b")}],
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=tmp_path)

        assert not (tmp_path / "bad.json").exists()

    def test_save_rejects_non_json_serializable_values_before_creating_directory(
        self, tmp_path
    ):
        target = tmp_path / "missing"
        ckpt = Checkpoint(
            session_id="bad",
            messages=[{"role": "assistant", "content": object()}],
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            save(ckpt, directory=target)

        assert not target.exists()

    def test_save_rejects_session_id_path_traversal(self, tmp_path):
        outside = tmp_path.parent / "escape.json"
        ckpt = Checkpoint(session_id="../escape", messages=[])

        with pytest.raises(ValueError, match="Invalid session_id"):
            save(ckpt, directory=tmp_path)

        assert not outside.exists()

    def test_save_rejects_invalid_session_id_before_creating_directory(self, tmp_path):
        target = tmp_path / "missing"
        ckpt = Checkpoint(session_id="../escape", messages=[])

        with pytest.raises(ValueError, match="Invalid session_id"):
            save(ckpt, directory=target)

        assert not target.exists()

    def test_load_rejects_session_id_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid session_id"):
            load("../escape", directory=tmp_path)

    def test_load_rejects_mismatched_session_id(self, tmp_path):
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "other", "messages": []}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Invalid checkpoint"):
            load("bad", directory=tmp_path)

    def test_save_rejects_whitespace_only_session_id(self, tmp_path):
        ckpt = Checkpoint(session_id="   ", messages=[])

        with pytest.raises(ValueError, match="Invalid session_id"):
            save(ckpt, directory=tmp_path)

    def test_save_rejects_non_string_session_id(self, tmp_path):
        ckpt = Checkpoint(session_id=123, messages=[])

        with pytest.raises(ValueError, match="Invalid session_id"):
            save(ckpt, directory=tmp_path)

    def test_load_rejects_whitespace_only_session_id(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid session_id"):
            load("   ", directory=tmp_path)

    def test_load_rejects_non_string_session_id(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid session_id"):
            load(123, directory=tmp_path)

    def test_long_session_id_roundtrips_with_safe_filename(self, tmp_path):
        long_id = "session_" + "x" * 300 + "a"
        ckpt = Checkpoint(session_id=long_id, messages=[{"role": "user", "content": "hi"}])

        path = save(ckpt, directory=tmp_path)
        loaded = load(long_id, directory=tmp_path)

        assert loaded.session_id == long_id
        assert loaded.messages == ckpt.messages
        assert len(path.name.encode("utf-8")) <= 255


class TestListCheckpoints:
    def test_empty_directory(self, tmp_path):
        assert list_checkpoints(directory=tmp_path) == []

    def test_lists_saved(self, tmp_path):
        save(Checkpoint(session_id="a", messages=[]), directory=tmp_path)
        save(Checkpoint(session_id="b", messages=[]), directory=tmp_path)
        result = list_checkpoints(directory=tmp_path)
        assert "a" in result
        assert "b" in result

    def test_lists_original_long_session_id(self, tmp_path):
        long_id = "session_" + "x" * 300 + "a"
        save(Checkpoint(session_id=long_id, messages=[]), directory=tmp_path)

        result = list_checkpoints(directory=tmp_path)

        assert result == [long_id]

    def test_list_uses_filename_for_non_string_session_id(self, tmp_path):
        save(Checkpoint(session_id="valid", messages=[]), directory=tmp_path)
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": 123, "messages": []}),
            encoding="utf-8",
        )

        result = list_checkpoints(directory=tmp_path)

        assert result == ["bad", "valid"]

    def test_list_uses_filename_for_invalid_session_id(self, tmp_path):
        save(Checkpoint(session_id="valid", messages=[]), directory=tmp_path)
        (tmp_path / "bad.json").write_text(
            json.dumps({"session_id": "../escape", "messages": []}),
            encoding="utf-8",
        )

        result = list_checkpoints(directory=tmp_path)

        assert result == ["bad", "valid"]

    def test_list_ignores_directory_named_like_checkpoint(self, tmp_path):
        save(Checkpoint(session_id="valid", messages=[]), directory=tmp_path)
        (tmp_path / "not-a-checkpoint.json").mkdir()

        result = list_checkpoints(directory=tmp_path)

        assert result == ["valid"]

    def test_nonexistent_directory(self, tmp_path):
        result = list_checkpoints(directory=tmp_path / "nope")
        assert result == []


class TestLatestCheckpoint:
    def test_returns_most_recent_checkpoint_by_file_mtime(self, tmp_path):
        older = save(Checkpoint(session_id="older", messages=[]), directory=tmp_path)
        newer = save(Checkpoint(session_id="newer", messages=[]), directory=tmp_path)
        older.touch()

        result = ckpt.latest_checkpoint(directory=tmp_path)

        assert result == "older"

    def test_returns_none_for_empty_directory(self, tmp_path):
        assert ckpt.latest_checkpoint(directory=tmp_path) is None

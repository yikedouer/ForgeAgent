"""记忆存储层测试 — forgecc.memory.store"""

from __future__ import annotations

import os
import time

import pytest

from forgecc.memory.store import (
    get_memory_dir,
    save_memory,
    list_memories,
    delete_memory,
    load_memory_index,
    update_index,
    _slugify,
    VALID_TYPES,
    MAX_INDEX_LINES,
    MAX_INDEX_BYTES,
)


class TestGetMemoryDir:
    def test_env_override(self, tmp_path, monkeypatch):
        override = tmp_path / "custom_mem"
        monkeypatch.setenv("FORGECC_MEMORY_DIR", str(override))
        result = get_memory_dir("/any/workspace")
        assert result == override
        assert result.exists()

    def test_env_override_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGECC_MEMORY_DIR", "~/memory")

        result = get_memory_dir("/any/workspace")

        assert result == home / "memory"
        assert result.exists()

    def test_auto_creates(self, tmp_path, monkeypatch):
        override = tmp_path / "new_mem_dir"
        monkeypatch.setenv("FORGECC_MEMORY_DIR", str(override))
        result = get_memory_dir("/ws")
        assert result.is_dir()


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        assert _slugify("user@home#1") == "user_home_1"

    def test_truncation(self):
        long = "a" * 100
        assert len(_slugify(long)) <= 40


class TestSaveMemory:
    def test_save_and_file_exists(self, tmp_memory_dir):
        filename = save_memory("/ws", "pref", "user prefers Chinese", "user", "# Pref")
        assert filename == "user_pref.md"
        assert (tmp_memory_dir / filename).exists()

    def test_invalid_type_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Invalid memory type"):
            save_memory("/ws", "x", "desc", "INVALID", "content")

    def test_non_string_type_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Invalid memory type"):
            save_memory("/ws", "pref", "desc", 123, "content")

    def test_type_trims_whitespace(self, tmp_memory_dir):
        filename = save_memory("/ws", "pref", "desc", " user ", "content")

        raw = (tmp_memory_dir / filename).read_text(encoding="utf-8")
        assert filename == "user_pref.md"
        assert "type: user" in raw

    def test_name_trims_whitespace(self, tmp_memory_dir):
        filename = save_memory("/ws", " pref ", "desc", "user", "content")

        raw = (tmp_memory_dir / filename).read_text(encoding="utf-8")
        assert filename == "user_pref.md"
        assert "name: pref" in raw

    def test_description_trims_whitespace(self, tmp_memory_dir):
        filename = save_memory("/ws", "pref", " desc ", "user", "content")

        raw = (tmp_memory_dir / filename).read_text(encoding="utf-8")
        assert "description: desc" in raw

    def test_blank_name_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory name"):
            save_memory("/ws", "   ", "desc", "user", "content")

    def test_non_string_name_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory name"):
            save_memory("/ws", 123, "desc", "user", "content")

    def test_blank_description_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory description"):
            save_memory("/ws", "pref", "   ", "user", "content")

    def test_non_string_description_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory description"):
            save_memory("/ws", "pref", 123, "user", "content")

    def test_blank_content_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory content"):
            save_memory("/ws", "pref", "desc", "user", "   ")

    def test_non_string_content_raises(self, tmp_memory_dir):
        with pytest.raises(ValueError, match="Memory content"):
            save_memory("/ws", "pref", "desc", "user", 123)

    def test_frontmatter_in_file(self, tmp_memory_dir):
        filename = save_memory("/ws", "test", "desc", "feedback", "body")
        raw = (tmp_memory_dir / filename).read_text()
        assert "---" in raw
        assert "name: test" in raw
        assert "type: feedback" in raw

    def test_index_updated(self, tmp_memory_dir):
        save_memory("/ws", "test", "desc", "project", "body")
        index = tmp_memory_dir / "MEMORY.md"
        assert index.exists()
        content = index.read_text()
        assert "test" in content

    def test_non_ascii_names_get_distinct_filenames(self, tmp_memory_dir):
        first = save_memory("/ws", "偏好", "first", "user", "body1")
        second = save_memory("/ws", "反馈", "second", "user", "body2")

        assert first != second
        assert (tmp_memory_dir / first).exists()
        assert (tmp_memory_dir / second).exists()

    def test_slug_collisions_do_not_overwrite_distinct_memories(self, tmp_memory_dir):
        first = save_memory("/ws", "Hello World", "first", "user", "body1")
        second = save_memory("/ws", "hello-world", "second", "user", "body2")

        assert first != second
        entries = list_memories("/ws")
        assert {entry.name for entry in entries} == {"Hello World", "hello-world"}
        assert (tmp_memory_dir / first).read_text(encoding="utf-8").endswith("body1")
        assert (tmp_memory_dir / second).read_text(encoding="utf-8").endswith("body2")

    def test_save_succeeds_when_index_path_is_directory(self, tmp_memory_dir):
        (tmp_memory_dir / "MEMORY.md").mkdir()

        filename = save_memory("/ws", "pref", "desc", "user", "body")

        assert filename == "user_pref.md"
        assert (tmp_memory_dir / filename).is_file()


class TestListMemories:
    def test_empty_dir(self, tmp_memory_dir):
        entries = list_memories("/ws")
        assert entries == []

    def test_mtime_descending(self, tmp_memory_dir):
        save_memory("/ws", "older", "first", "user", "c1")
        time.sleep(0.05)
        save_memory("/ws", "newer", "second", "user", "c2")
        entries = list_memories("/ws")
        assert len(entries) == 2
        assert entries[0].name == "newer"

    def test_skips_memory_index(self, tmp_memory_dir):
        save_memory("/ws", "test", "desc", "user", "body")
        entries = list_memories("/ws")
        filenames = [e.filename for e in entries]
        assert "MEMORY.md" not in filenames


class TestDeleteMemory:
    def test_delete_existing(self, tmp_memory_dir):
        filename = save_memory("/ws", "todel", "desc", "user", "body")
        assert delete_memory("/ws", filename) is True
        assert not (tmp_memory_dir / filename).exists()

    def test_delete_trims_filename(self, tmp_memory_dir):
        filename = save_memory("/ws", "todel", "desc", "user", "body")

        assert delete_memory("/ws", f" {filename} ") is True
        assert not (tmp_memory_dir / filename).exists()

    def test_delete_nonexistent(self, tmp_memory_dir):
        assert delete_memory("/ws", "nonexistent.md") is False

    def test_delete_rejects_whitespace_only_filename(self, tmp_memory_dir):
        suspicious = tmp_memory_dir / "   "
        suspicious.write_text("keep me", encoding="utf-8")

        assert delete_memory("/ws", "   ") is False
        assert suspicious.exists()

    def test_delete_rejects_non_string_filename(self, tmp_memory_dir):
        assert delete_memory("/ws", 123) is False

    def test_delete_rejects_path_traversal(self, tmp_memory_dir, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_text("keep me", encoding="utf-8")

        assert delete_memory("/ws", "../outside.md") is False
        assert outside.exists()

    def test_delete_rejects_backslash_path_separator(self, tmp_memory_dir):
        suspicious = tmp_memory_dir / "..\\outside.md"
        suspicious.write_text("keep me", encoding="utf-8")

        assert delete_memory("/ws", "..\\outside.md") is False
        assert suspicious.exists()

    def test_delete_rejects_memory_index(self, tmp_memory_dir):
        index = tmp_memory_dir / "MEMORY.md"
        index.write_text("# Index", encoding="utf-8")

        assert delete_memory("/ws", "MEMORY.md") is False
        assert index.exists()

    def test_delete_rejects_directory_named_like_memory(self, tmp_memory_dir):
        suspicious = tmp_memory_dir / "not_a_file.md"
        suspicious.mkdir()

        assert delete_memory("/ws", "not_a_file.md") is False
        assert suspicious.is_dir()


class TestLoadMemoryIndex:
    def test_no_index(self, tmp_memory_dir):
        result = load_memory_index("/ws")
        assert result == ""

    def test_invalid_utf8_index_returns_empty(self, tmp_memory_dir):
        index_path = tmp_memory_dir / "MEMORY.md"
        index_path.write_bytes(b"\xff\xfe\x00")

        result = load_memory_index("/ws")

        assert result == ""

    def test_line_truncation(self, tmp_memory_dir):
        index_path = tmp_memory_dir / "MEMORY.md"
        lines = [f"line {i}" for i in range(MAX_INDEX_LINES + 50)]
        index_path.write_text("\n".join(lines))
        result = load_memory_index("/ws")
        assert "truncated" in result

    def test_byte_truncation(self, tmp_memory_dir):
        index_path = tmp_memory_dir / "MEMORY.md"
        # 写入超过 25KB 的内容（单行以避免行截断先触发）
        index_path.write_text("x" * (MAX_INDEX_BYTES + 1000))
        result = load_memory_index("/ws")
        assert "truncated" in result

    def test_byte_truncation_respects_multibyte_utf8(self, tmp_memory_dir):
        index_path = tmp_memory_dir / "MEMORY.md"
        index_path.write_text("记" * MAX_INDEX_BYTES, encoding="utf-8")

        result = load_memory_index("/ws")

        assert "truncated" in result
        assert len(result.encode("utf-8")) <= MAX_INDEX_BYTES + 45

"""语义召回测试 — forgecc.memory.recall"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forgecc.memory.recall import (
    scan_memory_headers,
    format_memory_manifest,
    select_relevant_memories,
    memory_age,
    freshness_warning,
    format_memories_for_injection,
    RelevantMemory,
    MAX_MEMORY_FILES,
    MAX_MEMORY_BYTES_PER_FILE,
)
from forgecc.memory.store import save_memory


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _create_memory_file(mem_dir: Path, name: str, desc: str, type_: str, body: str):
    """直接在记忆目录写入一个记忆文件。"""
    text = f"---\nname: {name}\ndescription: {desc}\ntype: {type_}\n---\n{body}"
    filename = f"{type_}_{name.replace(' ', '_').lower()}.md"
    (mem_dir / filename).write_text(text, encoding="utf-8")
    return filename


# ═══════════════════════════════════════════════════════════════
# 1. memory_age / freshness_warning
# ═══════════════════════════════════════════════════════════════

class TestMemoryAge:
    def test_today(self):
        assert memory_age(time.time()) == "today"

    def test_yesterday(self):
        assert memory_age(time.time() - 86_400) == "yesterday"

    def test_days_ago(self):
        result = memory_age(time.time() - 86_400 * 5)
        assert "5 days ago" in result


class TestFreshnessWarning:
    def test_fresh_no_warning(self):
        assert freshness_warning(time.time()) == ""

    def test_stale_warning(self):
        old = time.time() - 86_400 * 10
        result = freshness_warning(old)
        assert "10 days old" in result
        assert "outdated" in result


# ═══════════════════════════════════════════════════════════════
# 2. scan_memory_headers
# ═══════════════════════════════════════════════════════════════

class TestScanMemoryHeaders:
    def test_invalid_workspace_returns_empty(self, monkeypatch):
        def fail_get_memory_dir(workspace):
            raise AssertionError("get_memory_dir should not be called")

        monkeypatch.setattr(
            "forgecc.memory.recall.get_memory_dir",
            fail_get_memory_dir,
        )

        assert scan_memory_headers(123) == []

    def test_scan_returns_headers(self, tmp_memory_dir):
        _create_memory_file(tmp_memory_dir, "pref", "user pref", "user", "body")
        headers = scan_memory_headers("/ws")
        assert len(headers) == 1
        assert headers[0].description == "user pref"

    def test_skips_memory_index(self, tmp_memory_dir):
        _create_memory_file(tmp_memory_dir, "test", "desc", "user", "body")
        # MEMORY.md 由 save_memory 调用 update_index 创建，这里手动创建
        (tmp_memory_dir / "MEMORY.md").write_text("# Index")
        headers = scan_memory_headers("/ws")
        filenames = [h.filename for h in headers]
        assert "MEMORY.md" not in filenames

    def test_mtime_sorted(self, tmp_memory_dir):
        _create_memory_file(tmp_memory_dir, "old", "first", "user", "c1")
        time.sleep(0.05)
        _create_memory_file(tmp_memory_dir, "new", "second", "user", "c2")
        headers = scan_memory_headers("/ws")
        assert headers[0].description == "second"

    def test_max_limit(self, tmp_memory_dir):
        for i in range(5):
            _create_memory_file(tmp_memory_dir, f"m{i}", f"desc{i}", "user", f"c{i}")
        headers = scan_memory_headers("/ws")
        assert len(headers) <= MAX_MEMORY_FILES


# ═══════════════════════════════════════════════════════════════
# 3. format_memory_manifest
# ═══════════════════════════════════════════════════════════════

class TestFormatMemoryManifest:
    def test_format(self, tmp_memory_dir):
        _create_memory_file(tmp_memory_dir, "test", "desc here", "feedback", "body")
        headers = scan_memory_headers("/ws")
        result = format_memory_manifest(headers)
        assert "[feedback]" in result
        assert "desc here" in result

    def test_no_description(self, tmp_memory_dir):
        # 创建无 description 的文件
        text = "---\nname: nodesc\ntype: user\n---\nbody"
        (tmp_memory_dir / "user_nodesc.md").write_text(text)
        headers = scan_memory_headers("/ws")
        result = format_memory_manifest(headers)
        assert "user_nodesc.md" in result


# ═══════════════════════════════════════════════════════════════
# 4. select_relevant_memories
# ═══════════════════════════════════════════════════════════════

class TestSelectRelevantMemories:
    def test_mock_provider_returns_selected(self, tmp_memory_dir):
        fname = _create_memory_file(tmp_memory_dir, "pref", "preference", "user", "content")
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": [fname]}
        )
        results = select_relevant_memories("query", "/ws", provider, set())
        assert len(results) == 1
        assert results[0].content.strip().endswith("content")

    def test_selects_from_first_json_object_when_response_has_extra_braces(
        self, tmp_memory_dir,
    ):
        fname = _create_memory_file(tmp_memory_dir, "pref", "preference", "user", "content")
        provider = MagicMock()
        provider.side_query.return_value = (
            json.dumps({"selected_memories": [fname]})
            + "\nExplanation: ignore this example {not json}."
        )

        results = select_relevant_memories("query", "/ws", provider, set())

        assert len(results) == 1
        assert results[0].content.strip().endswith("content")

    def test_accepts_single_selected_memory_string(self, tmp_memory_dir):
        fname = _create_memory_file(tmp_memory_dir, "pref", "preference", "user", "content")
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": fname}
        )

        results = select_relevant_memories("query", "/ws", provider, set())

        assert len(results) == 1
        assert results[0].content.strip().endswith("content")

    def test_ignores_non_string_selected_memory_items(self, tmp_memory_dir):
        fname = _create_memory_file(tmp_memory_dir, "pref", "preference", "user", "content")
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": [{"bad": "shape"}, 123, None, fname]}
        )

        results = select_relevant_memories("query", "/ws", provider, set())

        assert len(results) == 1
        assert results[0].content.strip().endswith("content")

    def test_filter_already_surfaced(self, tmp_memory_dir):
        fname = _create_memory_file(tmp_memory_dir, "pref", "desc", "user", "body")
        filepath = str(tmp_memory_dir / fname)
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": [fname]}
        )
        results = select_relevant_memories("q", "/ws", provider, {filepath})
        assert results == []

    def test_truncation_large_file(self, tmp_memory_dir):
        big_body = "x" * (MAX_MEMORY_BYTES_PER_FILE + 500)
        fname = _create_memory_file(tmp_memory_dir, "big", "big mem", "user", big_body)
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": [fname]}
        )
        results = select_relevant_memories("q", "/ws", provider, set())
        assert len(results) == 1
        assert "truncated" in results[0].content

    def test_truncation_large_multibyte_file_respects_byte_budget(self, tmp_memory_dir):
        big_body = "记" * MAX_MEMORY_BYTES_PER_FILE
        fname = _create_memory_file(tmp_memory_dir, "bigutf", "big utf", "user", big_body)
        provider = MagicMock()
        provider.side_query.return_value = json.dumps(
            {"selected_memories": [fname]}
        )

        results = select_relevant_memories("q", "/ws", provider, set())

        assert len(results) == 1
        assert "truncated" in results[0].content
        assert len(results[0].content.encode("utf-8")) <= MAX_MEMORY_BYTES_PER_FILE + 45

    def test_empty_no_memories(self, tmp_memory_dir):
        provider = MagicMock()
        results = select_relevant_memories("q", "/ws", provider, set())
        assert results == []


# ═══════════════════════════════════════════════════════════════
# 5. format_memories_for_injection
# ═══════════════════════════════════════════════════════════════

class TestFormatMemoriesForInjection:
    def test_non_list_returns_empty(self):
        assert format_memories_for_injection(None) == ""

    def test_skips_non_memory_items(self):
        mem = RelevantMemory(
            path="/path/to/mem.md",
            content="Memory content",
            mtime=time.time(),
            header="Memory header",
        )

        result = format_memories_for_injection([None, mem, object()])

        assert result.count("<system-reminder>") == 1
        assert "Memory header" in result
        assert "Memory content" in result

    def test_format(self):
        mem = RelevantMemory(
            path="/path/to/mem.md",
            content="Memory content",
            mtime=time.time(),
            header="Memory header",
        )
        result = format_memories_for_injection([mem])
        assert "<system-reminder>" in result
        assert "Memory header" in result
        assert "Memory content" in result

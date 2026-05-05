"""Frontmatter 解析测试 — forgeagent.frontmatter"""

from __future__ import annotations

from forgeagent.frontmatter import parse_frontmatter, format_frontmatter


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        text = "---\nname: test\ntype: user\n---\nBody content here."
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "test", "type": "user"}
        assert body == "Body content here."

    def test_no_frontmatter(self):
        text = "Just plain text, no frontmatter."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_missing_closing(self):
        text = "---\nname: test\ntype: user\nNo closing delimiter."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_text(self):
        meta, body = parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_roundtrip(self):
        original_meta = {"name": "test", "description": "a test memory", "type": "user"}
        original_body = "Memory content goes here."
        formatted = format_frontmatter(original_meta, original_body)
        meta, body = parse_frontmatter(formatted)
        assert meta == original_meta
        assert body == original_body

    def test_preserves_body_whitespace_after_separator_blank(self):
        text = "---\nname: code\ntype: reference\n---\n\n  indented\n\n"
        meta, body = parse_frontmatter(text)

        assert meta == {"name": "code", "type": "reference"}
        assert body == "  indented\n\n"

    def test_ignores_blank_keys(self):
        text = "---\n: bad\nname: code\n---\nBody"

        meta, body = parse_frontmatter(text)

        assert meta == {"name": "code"}
        assert body == "Body"


class TestFormatFrontmatter:
    def test_output_structure(self):
        result = format_frontmatter({"name": "x"}, "body")
        lines = result.split("\n")
        assert lines[0] == "---"
        assert "name: x" in result
        assert lines[-3] == "---"  # 倒数第三行是闭合分隔符
        assert "body" in result

    def test_meta_values_are_kept_single_line(self):
        formatted = format_frontmatter(
            {"description": "first line\nsecond line"},
            "body",
        )

        meta, body = parse_frontmatter(formatted)

        assert meta["description"] == "first line second line"
        assert body == "body"

    def test_blank_meta_keys_are_ignored(self):
        formatted = format_frontmatter({"": "bad", "name": "code"}, "body")

        assert "\n: bad\n" not in formatted
        meta, body = parse_frontmatter(formatted)
        assert meta == {"name": "code"}
        assert body == "body"

    def test_meta_keys_are_kept_single_line(self):
        formatted = format_frontmatter({"bad\nkey": "value"}, "body")

        assert "\nbad\nkey: value\n" not in formatted
        meta, body = parse_frontmatter(formatted)
        assert meta == {"bad key": "value"}
        assert body == "body"

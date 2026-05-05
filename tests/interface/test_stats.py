"""Workspace stats calculation tests."""


def test_count_workspace_lines_groups_by_extension(tmp_path):
    from forgeagent.interface.stats import count_workspace_lines

    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "README").write_text("title\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.py").write_text("three\n", encoding="utf-8")

    stats = count_workspace_lines(tmp_path)

    assert stats.total_files == 3
    assert stats.total_lines == 4
    assert stats.by_extension[".py"].files == 2
    assert stats.by_extension[".py"].lines == 3
    assert stats.by_extension["README"].files == 1
    assert stats.by_extension["README"].lines == 1


def test_count_workspace_lines_skips_generated_directories(tmp_path):
    from forgeagent.interface.stats import count_workspace_lines

    (tmp_path / "main.py").write_text("ok\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("bad\n", encoding="utf-8")
    (tmp_path / "pkg.egg-info").mkdir()
    (tmp_path / "pkg.egg-info" / "ignored.txt").write_text("bad\n", encoding="utf-8")

    stats = count_workspace_lines(tmp_path)

    assert stats.total_files == 1
    assert stats.total_lines == 1
    assert set(stats.by_extension) == {".py"}


def test_sorted_extensions_orders_by_line_count_descending(tmp_path):
    from forgeagent.interface.stats import count_workspace_lines

    (tmp_path / "a.py").write_text("1\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("1\n2\n", encoding="utf-8")

    stats = count_workspace_lines(tmp_path)

    assert [entry.extension for entry in stats.sorted_extensions()] == [".md", ".py"]

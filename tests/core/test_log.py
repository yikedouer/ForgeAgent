"""test_log.py — 日志初始化测试。"""

from __future__ import annotations

import logging
from pathlib import Path

import forgecc.core.log as flog


def _reset_logging_state() -> None:
    root = logging.getLogger("forgecc")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    flog._initialized = False


class TestLogSetup:
    def test_invalid_log_file_does_not_block_logger(self, tmp_path, monkeypatch):
        _reset_logging_state()
        monkeypatch.setenv("FORGECC_LOG_FILE", str(tmp_path))

        logger = flog.get_logger("forgecc.test")

        assert logger.name == "forgecc.test"
        assert logging.getLogger("forgecc").handlers
        _reset_logging_state()

    def test_log_file_expands_user_home(self, tmp_path, monkeypatch):
        _reset_logging_state()
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGECC_LOG_FILE", "~/logs/forgecc.log")
        monkeypatch.chdir(cwd)

        flog.get_logger("forgecc.test").info("hello")

        assert (home / "logs" / "forgecc.log").exists()
        assert not (cwd / "~" / "logs" / "forgecc.log").exists()
        _reset_logging_state()

    def test_log_file_trims_whitespace(self, tmp_path, monkeypatch):
        _reset_logging_state()
        log_file = tmp_path / "forgecc.log"
        monkeypatch.setenv("FORGECC_LOG_FILE", f" {log_file} ")

        flog.get_logger("forgecc.test").info("hello")

        assert log_file.exists()
        assert not (tmp_path / "forgecc.log ").exists()
        _reset_logging_state()

    def test_blank_log_file_uses_default_path(self, tmp_path, monkeypatch):
        _reset_logging_state()
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGECC_LOG_FILE", "   ")
        monkeypatch.chdir(cwd)

        flog.get_logger("forgecc.test").info("hello")

        assert (home / ".forgecc" / "logs" / "forgecc.log").exists()
        assert not (cwd / "forgecc.log").exists()
        _reset_logging_state()

    def test_log_level_trims_whitespace(self, tmp_path, monkeypatch):
        _reset_logging_state()
        monkeypatch.setenv("FORGECC_LOG_FILE", str(tmp_path / "forgecc.log"))
        monkeypatch.setenv("FORGECC_LOG_LEVEL", " INFO ")

        flog.get_logger("forgecc.test")

        assert logging.getLogger("forgecc").level == logging.INFO
        _reset_logging_state()

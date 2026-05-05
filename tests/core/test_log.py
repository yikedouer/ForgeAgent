"""test_log.py — 日志初始化测试。"""

from __future__ import annotations

import logging
from pathlib import Path

import forgeagent.core.log as flog


def _reset_logging_state() -> None:
    root = logging.getLogger("forgeagent")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    flog._initialized = False


class TestLogSetup:
    def test_invalid_log_file_does_not_block_logger(self, tmp_path, monkeypatch):
        _reset_logging_state()
        monkeypatch.setenv("FORGEAGENT_LOG_FILE", str(tmp_path))

        logger = flog.get_logger("forgeagent.test")

        assert logger.name == "forgeagent.test"
        assert logging.getLogger("forgeagent").handlers
        _reset_logging_state()

    def test_log_file_expands_user_home(self, tmp_path, monkeypatch):
        _reset_logging_state()
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGEAGENT_LOG_FILE", "~/logs/forgeagent.log")
        monkeypatch.chdir(cwd)

        flog.get_logger("forgeagent.test").info("hello")

        assert (home / "logs" / "forgeagent.log").exists()
        assert not (cwd / "~" / "logs" / "forgeagent.log").exists()
        _reset_logging_state()

    def test_log_file_trims_whitespace(self, tmp_path, monkeypatch):
        _reset_logging_state()
        log_file = tmp_path / "forgeagent.log"
        monkeypatch.setenv("FORGEAGENT_LOG_FILE", f" {log_file} ")

        flog.get_logger("forgeagent.test").info("hello")

        assert log_file.exists()
        assert not (tmp_path / "forgeagent.log ").exists()
        _reset_logging_state()

    def test_blank_log_file_uses_default_path(self, tmp_path, monkeypatch):
        _reset_logging_state()
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGEAGENT_LOG_FILE", "   ")
        monkeypatch.chdir(cwd)

        flog.get_logger("forgeagent.test").info("hello")

        assert (home / ".forgeagent" / "logs" / "forgeagent.log").exists()
        assert not (cwd / "forgeagent.log").exists()
        _reset_logging_state()

    def test_log_level_trims_whitespace(self, tmp_path, monkeypatch):
        _reset_logging_state()
        monkeypatch.setenv("FORGEAGENT_LOG_FILE", str(tmp_path / "forgeagent.log"))
        monkeypatch.setenv("FORGEAGENT_LOG_LEVEL", " INFO ")

        flog.get_logger("forgeagent.test")

        assert logging.getLogger("forgeagent").level == logging.INFO
        _reset_logging_state()

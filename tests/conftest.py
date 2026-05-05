"""共享测试 fixtures。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# Keep tests hermetic even when the real user-level ForgeAgent directory is not writable.
os.environ.setdefault("FORGEAGENT_LOG_FILE", "/private/tmp/forgeagent-test.log")

from forgeagent.toolkit import _CATALOG, _enforcer
from forgeagent.core.settings import Settings


# ── 用户级状态目录隔离 ─────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_session_dir(tmp_path, monkeypatch):
    """将会话检查点和工具结果隔离到测试临时目录。"""
    monkeypatch.setenv("FORGEAGENT_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("FORGEAGENT_PLANS_DIR", str(tmp_path / "plans"))


# ── 工具目录隔离 ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_catalog():
    """每个测试前保存并清空工具目录，测试后还原。"""
    import forgeagent.toolkit as tk
    saved_catalog = dict(tk._CATALOG)
    saved_enforcer = tk._enforcer
    tk._CATALOG.clear()
    tk._enforcer = None
    yield
    tk._CATALOG.clear()
    tk._CATALOG.update(saved_catalog)
    tk._enforcer = saved_enforcer


# ── 临时工作区 ────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path):
    """返回临时工作目录。"""
    return str(tmp_path)


# ── Settings fixture ──────────────────────────────────────

@pytest.fixture
def mock_settings(tmp_workspace):
    """预填充的 Settings 实例。"""
    return Settings(
        api_key="test-key",
        base_url="https://test.example.com/v1",
        model="test-model",
        context_budget=128000,
        max_rounds=60,
        workspace=tmp_workspace,
        permission_mode="prompt",
    )


# ── Mock Provider ─────────────────────────────────────────

@pytest.fixture
def mock_provider():
    """可控返回值的 Mock Provider。"""
    provider = MagicMock()
    provider.side_query.return_value = ""
    provider.tokens_used = (0, 0)
    provider._total_in = 0
    provider._total_out = 0
    return provider


# ── 临时记忆目录 ──────────────────────────────────────────

@pytest.fixture
def tmp_memory_dir(tmp_path, monkeypatch):
    """设置 FORGEAGENT_MEMORY_DIR 到临时目录。"""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    monkeypatch.setenv("FORGEAGENT_MEMORY_DIR", str(mem_dir))
    return mem_dir

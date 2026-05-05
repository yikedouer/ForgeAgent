"""test_permissions.py — 权限矩阵测试。"""

from __future__ import annotations

import os

import pytest

from forgecc.core.permissions import (
    PermissionMode,
    PermissionEnforcer,
    check_workspace_boundary,
    RISK_READ,
    RISK_WRITE,
    RISK_DANGER,
)


# ═══════════════════════════════════════════════════════════
# 5.1 权限模式 × 风险级别矩阵
# ═══════════════════════════════════════════════════════════

class TestPermissionMatrix:
    """15 个组合：5 模式 × 3 风险级别。"""

    def _enforcer(self, mode: PermissionMode, ws="/tmp/test"):
        return PermissionEnforcer(mode, ws)

    # -- DANGER 模式：全允许 --
    def test_danger_read(self):
        assert self._enforcer(PermissionMode.DANGER)._check_mode("t", RISK_READ) is None

    def test_danger_write(self):
        assert self._enforcer(PermissionMode.DANGER)._check_mode("t", RISK_WRITE) is None

    def test_danger_danger(self):
        assert self._enforcer(PermissionMode.DANGER)._check_mode("t", RISK_DANGER) is None

    def test_unknown_risk_is_denied_even_in_danger_mode(self):
        result = self._enforcer(PermissionMode.DANGER)._check_mode("t", "writee")
        assert result is not None
        assert "unknown risk" in result

    def test_non_string_risk_is_denied_without_crashing(self):
        result = self._enforcer(PermissionMode.DANGER)._check_mode("t", ["danger"])
        assert result is not None
        assert "unknown risk" in result

    # -- WRITE 模式：read+write 允许，danger 拒绝 --
    def test_write_read(self):
        assert self._enforcer(PermissionMode.WRITE)._check_mode("t", RISK_READ) is None

    def test_write_write(self):
        assert self._enforcer(PermissionMode.WRITE)._check_mode("t", RISK_WRITE) is None

    def test_write_danger(self):
        result = self._enforcer(PermissionMode.WRITE)._check_mode("t", RISK_DANGER)
        assert result is not None
        assert "DENIED" in result

    # -- READONLY 模式：仅 read 允许 --
    def test_readonly_read(self):
        assert self._enforcer(PermissionMode.READONLY)._check_mode("t", RISK_READ) is None

    def test_readonly_write(self):
        result = self._enforcer(PermissionMode.READONLY)._check_mode("t", RISK_WRITE)
        assert result is not None

    def test_readonly_danger(self):
        result = self._enforcer(PermissionMode.READONLY)._check_mode("t", RISK_DANGER)
        assert result is not None

    # -- PLAN 模式：仅 read 允许 --
    def test_plan_read(self):
        assert self._enforcer(PermissionMode.PLAN)._check_mode("t", RISK_READ) is None

    def test_plan_write(self):
        result = self._enforcer(PermissionMode.PLAN)._check_mode("t", RISK_WRITE)
        assert result is not None
        assert "plan mode" in result

    def test_plan_danger(self):
        result = self._enforcer(PermissionMode.PLAN)._check_mode("t", RISK_DANGER)
        assert result is not None

    # -- PROMPT 模式：read+write 自动允许，danger 询问 --
    def test_prompt_read(self):
        assert self._enforcer(PermissionMode.PROMPT)._check_mode("t", RISK_READ) is None

    def test_prompt_write(self):
        assert self._enforcer(PermissionMode.PROMPT)._check_mode("t", RISK_WRITE) is None

    def test_prompt_danger_no_prompter(self):
        """未设置 prompter 时 danger 被拒。"""
        result = self._enforcer(PermissionMode.PROMPT)._check_mode("t", RISK_DANGER)
        assert result is not None
        assert "requires confirmation" in result


# ═══════════════════════════════════════════════════════════
# 5.2 PROMPT 模式交互
# ═══════════════════════════════════════════════════════════

class TestPromptInteraction:
    def test_prompter_allows(self):
        e = PermissionEnforcer(PermissionMode.PROMPT, "/tmp")
        e.set_prompter(lambda name, args: True)
        assert e._check_mode("shell", RISK_DANGER) is None

    def test_prompter_denies(self):
        e = PermissionEnforcer(PermissionMode.PROMPT, "/tmp")
        e.set_prompter(lambda name, args: False)
        result = e._check_mode("shell", RISK_DANGER)
        assert result is not None
        assert "rejected" in result

    def test_prompter_receives_tool_args(self):
        e = PermissionEnforcer(PermissionMode.PROMPT, "/tmp")
        seen = {}

        def prompter(name, args):
            seen["name"] = name
            seen["args"] = args
            return True

        e.set_prompter(prompter)

        result = e.check("shell", RISK_DANGER, {"command": "git status"})

        assert result is None
        assert seen == {"name": "shell", "args": {"command": "git status"}}

    def test_prompter_error_denies_without_crashing(self):
        e = PermissionEnforcer(PermissionMode.PROMPT, "/tmp")

        def broken_prompter(name, args):
            raise RuntimeError("terminal unavailable")

        e.set_prompter(broken_prompter)

        result = e.check("shell", RISK_DANGER, {"command": "git status"})

        assert result is not None
        assert "confirmation failed" in result

    def test_no_prompter_denies(self):
        e = PermissionEnforcer(PermissionMode.PROMPT, "/tmp")
        result = e._check_mode("shell", RISK_DANGER)
        assert result is not None


# ═══════════════════════════════════════════════════════════
# 5.3 工作区边界检查
# ═══════════════════════════════════════════════════════════

class TestWorkspaceBoundary:
    def test_inside_workspace(self, tmp_path):
        f = tmp_path / "test.py"
        f.touch()
        assert check_workspace_boundary(str(f), str(tmp_path)) is None

    def test_outside_workspace(self, tmp_path):
        result = check_workspace_boundary("/etc/passwd", str(tmp_path))
        assert result is not None
        assert "outside workspace" in result

    def test_traversal_attack(self, tmp_path):
        evil = str(tmp_path / ".." / ".." / "etc" / "passwd")
        result = check_workspace_boundary(evil, str(tmp_path))
        assert result is not None

    def test_no_path_arg_skips_check(self, tmp_path):
        """check() 方法在无 path 参数时跳过边界检查。"""
        e = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))
        # 无 path/file/filepath 键 → 边界检查不触发
        assert e.check("some_tool", RISK_WRITE, {"text": "hi"}) is None

    def test_write_tool_outside_workspace(self, tmp_path):
        """write 工具访问工作区外路径应被拒。"""
        e = PermissionEnforcer(PermissionMode.DANGER, str(tmp_path))
        # DANGER 模式下模式检查通过，但边界检查仍执行于 write 级别
        # 注意：permissions.py 仅对 RISK_WRITE 级别执行边界检查
        e2 = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))
        result = e2.check("write_file", RISK_WRITE, {"path": "/etc/shadow"})
        assert result is not None

    def test_write_tool_outside_workspace_with_file_path_arg(self, tmp_path):
        """write 工具使用 file_path 参数名时也应被工作区边界拦截。"""
        e = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))

        result = e.check("custom_writer", RISK_WRITE, {"file_path": "/etc/shadow"})

        assert result is not None
        assert "outside workspace" in result

    def test_all_path_like_args_are_checked(self, tmp_path):
        """多路径工具中任一路径越界都应被拦截。"""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        e = PermissionEnforcer(PermissionMode.WRITE, str(workspace))

        result = e.check(
            "copy_file",
            RISK_WRITE,
            {"path": "inside.txt", "file_path": "/etc/shadow"},
        )

        assert result is not None
        assert "outside workspace" in result

    def test_read_tool_outside_workspace_is_denied(self, tmp_path):
        """read 工具同样不能读取工作区外路径。"""
        e = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))

        result = e.check("read_file", RISK_READ, {"path": "/etc/passwd"})

        assert result is not None
        assert "outside workspace" in result

    def test_read_tool_root_outside_workspace_is_denied(self, tmp_path):
        """搜索类 read 工具使用 root 参数时也应受工作区边界限制。"""
        e = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))

        result = e.check("grep_search", RISK_READ, {"root": "/etc"})

        assert result is not None
        assert "outside workspace" in result

    def test_relative_write_path_is_resolved_against_workspace(self, tmp_path, monkeypatch):
        """相对写路径应按配置的 workspace 解析，而不是按进程 cwd 解析。"""
        workspace = tmp_path / "workspace"
        other = tmp_path / "other"
        workspace.mkdir()
        other.mkdir()
        monkeypatch.chdir(other)
        e = PermissionEnforcer(PermissionMode.WRITE, str(workspace))

        result = e.check("write_file", RISK_WRITE, {"path": "notes.md"})

        assert result is None

    def test_non_object_args_are_denied_without_crashing(self, tmp_path):
        """权限检查直接收到异常参数时应拒绝，而不是抛 AttributeError。"""
        e = PermissionEnforcer(PermissionMode.WRITE, str(tmp_path))

        result = e.check("write_file", RISK_WRITE, ["bad"])

        assert result is not None
        assert "arguments" in result


# ═══════════════════════════════════════════════════════════
# 5.4 模式切换
# ═══════════════════════════════════════════════════════════

class TestModeSwitch:
    def test_set_mode(self):
        e = PermissionEnforcer(PermissionMode.READONLY, "/tmp")
        assert e.mode == PermissionMode.READONLY
        e.mode = PermissionMode.DANGER
        assert e.mode == PermissionMode.DANGER

    def test_switch_takes_effect_immediately(self):
        e = PermissionEnforcer(PermissionMode.READONLY, "/tmp")
        assert e._check_mode("t", RISK_WRITE) is not None  # 被拒
        e.mode = PermissionMode.WRITE
        assert e._check_mode("t", RISK_WRITE) is None  # 允许

"""test_plan_mode.py — 计划模式测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecc.core.plan_mode import (
    generate_plan_file_path,
    build_plan_mode_prompt,
    PLAN_TOOL_NAMES,
    PLAN_TOOL_DEFS,
    EDIT_TOOL_NAMES,
    PlanModeController,
)
from forgecc.core.permissions import PermissionMode, PermissionEnforcer


class TestPlanConstants:
    def test_plan_tool_names(self):
        assert PLAN_TOOL_NAMES == {"enter_plan_mode", "exit_plan_mode"}

    def test_edit_tool_names(self):
        assert EDIT_TOOL_NAMES == {"write_file", "edit_file"}

    def test_plan_tool_defs_format(self):
        assert len(PLAN_TOOL_DEFS) == 2
        for defn in PLAN_TOOL_DEFS:
            assert "name" in defn
            assert "description" in defn
            assert "parameters" in defn
            assert defn["name"] in PLAN_TOOL_NAMES


class TestGeneratePlanFilePath:
    def test_uses_env_plans_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))

        path = generate_plan_file_path("env123")

        assert path == tmp_path / "plan-env123.md"
        assert path.parent.is_dir()

    def test_env_plans_dir_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGECC_PLANS_DIR", "~/plans")

        path = generate_plan_file_path("env123")

        assert path == home / "plans" / "plan-env123.md"
        assert path.parent.is_dir()

    def test_returns_expected_path(self):
        path = generate_plan_file_path("abc123")
        assert path.name == "plan-abc123.md"
        assert path.parent.name == "plans"

    def test_directory_created(self):
        path = generate_plan_file_path("test_session")
        assert path.parent.is_dir()

    def test_rejects_session_id_path_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))

        with pytest.raises(ValueError, match="Invalid session_id"):
            generate_plan_file_path("../escape")

        assert not (tmp_path.parent / "plan-escape.md").exists()

    def test_long_session_id_uses_safe_filename(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))
        long_id = "session_" + "x" * 300 + "a"

        path = generate_plan_file_path(long_id)

        assert path.parent == tmp_path
        assert path.name.startswith("plan-session_")
        assert path.name.endswith(".md")
        assert len(path.name.encode("utf-8")) <= 255


class TestBuildPlanModePrompt:
    def test_contains_plan_file_path(self):
        prompt = build_plan_mode_prompt("/tmp/plan.md")
        assert "/tmp/plan.md" in prompt

    def test_contains_constraints(self):
        prompt = build_plan_mode_prompt("/tmp/plan.md")
        assert "Plan Mode Active" in prompt
        assert "MUST NOT" in prompt
        assert "exit_plan_mode" in prompt


class TestPlanModeController:
    def test_toggle_enter_sets_plan_mode_and_plan_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))
        enforcer = PermissionEnforcer(PermissionMode.PROMPT, tmp_path)
        controller = PlanModeController(
            session_id=lambda: "abc123",
            enforcer=enforcer,
            transcript=[],
        )

        mode = controller.toggle()

        assert mode == "plan"
        assert enforcer.mode == PermissionMode.PLAN
        assert controller.plan_file_path == str(tmp_path / "plan-abc123.md")

    def test_exit_without_approval_restores_previous_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))
        enforcer = PermissionEnforcer(PermissionMode.WRITE, tmp_path)
        controller = PlanModeController(
            session_id=lambda: "abc123",
            enforcer=enforcer,
            transcript=[],
        )

        controller.execute_tool("enter_plan_mode")
        result = controller.execute_tool("exit_plan_mode")

        assert "Permission mode restored to: write" in result
        assert enforcer.mode == PermissionMode.WRITE
        assert controller.plan_file_path is None

    def test_filter_blocks_shell_and_appends_tool_result(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_PLANS_DIR", str(tmp_path))
        transcript: list[dict] = []
        enforcer = PermissionEnforcer(PermissionMode.PROMPT, tmp_path)
        controller = PlanModeController(
            session_id=lambda: "abc123",
            enforcer=enforcer,
            transcript=transcript,
        )
        controller.execute_tool("enter_plan_mode")

        result = controller.filter_calls([(["bad"], "shell", {"command": "ls"})])

        assert result == []
        assert transcript == [
            {
                "role": "tool",
                "tool_call_id": "call_0",
                "content": "[plan mode] Shell commands are blocked in plan mode.",
            }
        ]

"""Engine-facing plan-mode compatibility API."""

from __future__ import annotations

from .plan_mode import PlanApprovalFn


class EnginePlanApiMixin:
    """Compatibility properties/methods delegating to PlanModeController."""

    @property
    def _pre_plan_mode(self) -> str | None:
        return self._plan.pre_plan_mode

    @_pre_plan_mode.setter
    def _pre_plan_mode(self, value: str | None) -> None:
        self._plan.pre_plan_mode = value

    @property
    def _plan_file_path(self) -> str | None:
        return self._plan.plan_file_path

    @_plan_file_path.setter
    def _plan_file_path(self, value: str | None) -> None:
        self._plan.plan_file_path = value

    @property
    def _plan_approval_fn(self) -> PlanApprovalFn | None:
        return self._plan.approval_fn

    @_plan_approval_fn.setter
    def _plan_approval_fn(self, value: PlanApprovalFn | None) -> None:
        self._plan.approval_fn = value

    @property
    def _context_cleared(self) -> bool:
        return self._plan.context_cleared

    @_context_cleared.setter
    def _context_cleared(self, value: bool) -> None:
        self._plan.context_cleared = value

    def set_plan_approval_fn(self, fn: PlanApprovalFn) -> None:
        """Inject the interactive plan approval callback."""
        self._plan.set_approval_fn(fn)

    def toggle_plan_mode(self) -> str:
        """Toggle plan mode and return the active permission mode name."""
        mode = self._plan.toggle()
        if mode == "plan":
            self._log.info("进入计划模式  plan_file=%s", self._plan_file_path)
        else:
            self._log.info("退出计划模式 → %s", mode)
        return mode

    def _execute_plan_tool(self, name: str) -> str:
        """Handle enter_plan_mode / exit_plan_mode tool calls."""
        result = self._plan.execute_tool(name)
        if self._plan.context_cleared:
            self._collapse = None
        return result

    def _handle_approval(self, result: dict, plan_content: str) -> str:
        """Handle approval callback output."""
        output = self._plan.handle_approval(result, plan_content)
        if self._plan.context_cleared:
            self._collapse = None
        return output

    def _filter_plan_mode_calls(
        self, calls: list[tuple[str, str, object]]
    ) -> list[tuple[str, str, object]]:
        """Return calls allowed by plan mode, appending denials to transcript."""
        return self._plan.filter_calls(calls)

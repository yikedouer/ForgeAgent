"""Interactive plan approval prompt."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


PlanApprovalFn = Callable[[str], Awaitable[dict]]


def build_plan_approval_fn(console: Any) -> PlanApprovalFn:
    """Build the async callback used by Engine when exiting plan mode."""

    async def _plan_approval(plan_content: str) -> dict:
        console.print("\n  [cyan]━━━ Plan for Approval ━━━[/cyan]")
        lines = plan_content.split("\n")
        max_lines = 60
        for line in lines[:max_lines]:
            console.print(f"  {line}")
        if len(lines) > max_lines:
            console.print(f"  [dim]... ({len(lines) - max_lines} more lines)[/dim]")
        console.print("  [cyan]━━━━━━━━━━━━━━━━━━━━━━━━[/cyan]\n")

        console.print("  [bold yellow]Proceed with this plan?[/bold yellow]")
        console.print("    y) Continue")
        console.print("    n) Stay in planning")

        while True:
            try:
                choice = console.input("  Proceed with this plan? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return {"choice": "keep-planning", "feedback": "Cancelled by user."}

            if choice in {"y", "yes"}:
                return {"choice": "execute"}
            if choice in {"", "n", "no"}:
                return {
                    "choice": "keep-planning",
                    "feedback": "User chose not to execute the plan.",
                }
            console.print("  [yellow]Please enter y or n.[/yellow]")

    return _plan_approval

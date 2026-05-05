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

        console.print("  [bold yellow]Choose an option:[/bold yellow]")
        console.print("    1) Yes, clear context and execute [dim]— fresh start with auto-accept edits[/dim]")
        console.print("    2) Yes, and execute [dim]— keep context, auto-accept edits[/dim]")
        console.print("    3) Yes, manually approve edits [dim]— keep context, confirm each edit[/dim]")
        console.print("    4) No, keep planning [dim]— provide feedback to revise[/dim]")

        while True:
            try:
                choice = console.input("  Enter choice (1-4): ").strip()
            except (EOFError, KeyboardInterrupt):
                return {"choice": "keep-planning", "feedback": "Cancelled by user."}

            if choice == "1":
                return {"choice": "clear-and-execute"}
            if choice == "2":
                return {"choice": "execute"}
            if choice == "3":
                return {"choice": "manual-execute"}
            if choice == "4":
                try:
                    feedback = console.input("  Feedback (what to change): ").strip()
                except (EOFError, KeyboardInterrupt):
                    feedback = ""
                return {"choice": "keep-planning", "feedback": feedback or None}
            console.print("  [yellow]Invalid choice. Enter 1, 2, 3, or 4.[/yellow]")

    return _plan_approval

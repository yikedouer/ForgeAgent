"""Command mixin for the interactive REPL."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..context import checkpoint as ckpt
from ..instruments.skill import skill as invoke_skill
from ..memory.store import get_memory_dir, list_memories, save_memory
from ..skills import playbook
from .export import render_transcript_markdown
from .stats import count_workspace_lines


class ForgeReplCommandMixin:
    """Built-in slash aliases, skills, and REPL commands."""

    def _invoke_slash_builtin(self, line: str) -> bool:
        parts = line[1:].lstrip().split(maxsplit=1)
        if not parts:
            return False
        name = parts[0].strip()
        arg = parts[1] if len(parts) > 1 else ""
        if not name:
            return False

        command = getattr(self, f"do_{name}", None)
        if command is None:
            return False
        command(arg)
        return True

    def _invoke_skill(self, line: str) -> None:
        parts = line[1:].lstrip().split(maxsplit=1)
        if not parts:
            self._console.print("[yellow]Unknown skill ''. No skill name provided.[/yellow]")
            return
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        pb = playbook.find(name)
        if pb is None:
            available = [p.name for p in playbook.discover()]
            if available:
                self._console.print(
                    f"[yellow]Unknown skill '{name}'. Available: {', '.join(available)}[/yellow]"
                )
            else:
                self._console.print(f"[yellow]Unknown skill '{name}'. No skills installed.[/yellow]")
                self._console.print("[dim]Add skills to .forgecc/skills/<name>/SKILL.md[/dim]")
            return

        if not pb.user_invocable:
            self._console.print(f"[yellow]Skill '{name}' is auto-only (not user-invocable).[/yellow]")
            return

        self._console.print(f"  [dim]\u26a1 Invoking skill: {name}[/dim]")
        try:
            if pb.mode == "fork":
                answer = invoke_skill(name, args)
                if answer:
                    self._console.print(answer)
                return

            prompt = playbook.resolve_template(pb, args)
            answer = self.engine.run(
                prompt,
                on_token=self._on_token,
                on_instrument=self._on_instrument,
            )
            if answer:
                self._console.print()
        except KeyboardInterrupt:
            self._console.print("\n[yellow]interrupted[/yellow]")
        except Exception as exc:
            self._console.print(f"\n[red]Skill error: {exc}[/red]")

    def do_help(self, arg: str) -> None:
        commands = [
            ("help", "Show this help message"),
            ("save", "Save the current session to disk"),
            ("sessions", "List saved sessions"),
            ("usage", "Show token usage statistics"),
            ("cost", "Estimate token cost for this session"),
            ("skills", "List available skills"),
            ("plan", "Toggle plan mode (read-only planning phase)"),
            ("model [name]", "Show or switch the current model"),
            ("compact", "Manually trigger conversation compaction"),
            ("clear", "Clear the current conversation"),
            ("memory", "List persistent memories for this project"),
            ("remember <text>", "Quick-save a feedback memory"),
            ("diff", "Show files modified in this session (git diff)"),
            ("export [file]", "Export current conversation as Markdown"),
            ("stats", "Count lines of code in current workspace"),
            ("exit / quit", "Exit the REPL"),
        ]
        self._console.print("\n[bold]Commands[/bold] (prefix with nothing, just type):")
        for name, desc in commands:
            self._console.print(f"  [cyan]{name:<16}[/cyan] {desc}")
        self._console.print("\n[bold]Skills[/bold] (prefix with /):\n  /skillname [args]")

    def do_save(self, _arg: str) -> None:
        path = self.engine.save_checkpoint()
        self._console.print(f"[green]Session saved → {path}[/green]")

    def do_sessions(self, _arg: str) -> None:
        ids = ckpt.list_checkpoints()
        if not ids:
            self._console.print("[dim]No saved sessions.[/dim]")
        else:
            for sid in ids:
                self._console.print(f"  {sid}")

    def do_usage(self, _arg: str) -> None:
        t_in, t_out = self._tokens_used()
        self._console.print(f"  Tokens in: {t_in:,}  |  Tokens out: {t_out:,}")

    def do_skills(self, _arg: str) -> None:
        pbs = playbook.discover()
        if not pbs:
            self._console.print("[dim]No skills installed. Add to .forgecc/skills/<name>/SKILL.md[/dim]")
            return
        for pb in pbs:
            tag = "inline" if pb.mode == "inline" else "fork"
            inv = "" if pb.user_invocable else " [auto-only]"
            self._console.print(f"  /{pb.name} [{tag}]{inv} — {pb.description}")

    def do_plan(self, _arg: str) -> None:
        new_mode = self.engine.toggle_plan_mode()
        if new_mode == "plan":
            self._console.print(
                f"  [bold cyan]Entered plan mode (read-only).[/bold cyan]\n"
                f"  Plan file: {self.engine._plan.plan_file_path}\n"
                f"  [dim]Use read tools to explore, then describe your task. "
                f"Agent will write a plan for your approval.[/dim]"
            )
        else:
            self._console.print(f"  [green]Exited plan mode → {new_mode} mode[/green]")

    def do_cost(self, _arg: str) -> None:
        t_in, t_out = self._tokens_used()
        cost_in = t_in * 0.002 / 1000
        cost_out = t_out * 0.006 / 1000
        total = cost_in + cost_out
        self._console.print(f"  Tokens in: {t_in:,} (~${cost_in:.4f})")
        self._console.print(f"  Tokens out: {t_out:,} (~${cost_out:.4f})")
        self._console.print(f"  [bold]Estimated total: ${total:.4f}[/bold]")

    def _tokens_used(self) -> tuple[int, int]:
        fallback = self.engine.provider.tokens_used
        return (
            getattr(self.engine, "_total_input_tokens", fallback[0]),
            getattr(self.engine, "_total_output_tokens", fallback[1]),
        )

    def do_model(self, arg: str) -> None:
        if not arg.strip():
            self._console.print(f"  Current model: [cyan]{self.engine.settings.model}[/cyan]")
            self._console.print(f"  Base URL: {self.engine.settings.base_url}")
            return
        self.engine.switch_model(arg.strip())
        self._console.print(f"  [green]Switched to model: {self.engine.settings.model}[/green]")
        self._console.print(f"  [dim]Base URL: {self.engine.settings.base_url}[/dim]")

    def do_compact(self, _arg: str) -> None:
        report = self.engine.compact_conversation()
        if report.result.performed:
            self._console.print(
                f"  [green]Compacted: {report.before_messages} → {report.after_messages} messages, "
                f"{report.before_tokens:,} → {report.after_tokens:,} est. tokens[/green]"
            )
            if report.result.collapse:
                self._console.print("  [dim]Context Collapse active (reversible projection)[/dim]")
        else:
            pct = report.before_tokens / report.context_budget * 100 if report.context_budget else 0
            self._console.print(f"  [dim]No compaction needed ({pct:.0f}% of budget).[/dim]")

    def do_clear(self, _arg: str) -> None:
        self.engine.clear_conversation()
        self._console.print("  [green]Conversation cleared (collapse + memory + plan mode reset).[/green]")

    def do_diff(self, _arg: str) -> None:
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                cwd=self.engine.settings.workspace,
            )
            output = result.stdout.strip()
            if output:
                self._console.print(output)
            else:
                self._console.print("  [dim]No changes detected (git diff empty).[/dim]")
        except Exception as exc:
            self._console.print(f"  [red]git diff failed: {exc}[/red]")

    def do_export(self, arg: str) -> None:
        output = Path(arg.strip() or f"forgecc-{self.engine.session_id}.md").expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        markdown = render_transcript_markdown(self.engine.session_id, self.engine.transcript)
        output.write_text(markdown, encoding="utf-8")
        self._console.print(f"  [green]Exported conversation → {output}[/green]")

    def do_memory(self, _arg: str) -> None:
        workspace = self.engine.settings.workspace
        entries = list_memories(workspace)
        if not entries:
            mem_dir = get_memory_dir(workspace)
            self._console.print(f"  [dim]No memories saved yet.  Dir: {mem_dir}[/dim]")
            return
        self._console.print(f"\n  [bold]Memories[/bold] ({len(entries)} total):\n")
        for e in entries:
            from ..memory.recall import memory_age
            age = memory_age(e.mtime)
            self._console.print(f"  [cyan]{e.filename}[/cyan]  [{e.type}]  ({age})")
            self._console.print(f"    {e.name} — {e.description}")

    def do_remember(self, arg: str) -> None:
        text = arg.strip()
        if not text:
            self._console.print("  [yellow]Usage: remember <text>[/yellow]")
            self._console.print("  [dim]Example: remember always respond in Chinese[/dim]")
            return
        filename = save_memory(
            self.engine.settings.workspace,
            name=text[:60],
            description=text[:120],
            type_="feedback",
            content=text,
        )
        self._console.print(f"  [green]Memory saved → {filename}[/green]")

    def do_stats(self, _arg: str) -> None:
        workspace = self.engine.settings.workspace
        stats = count_workspace_lines(workspace)
        if not stats.by_extension:
            self._console.print("  [dim]No files found.[/dim]")
            return

        self._console.print(f"\n  [bold]Workspace:[/bold] {workspace}\n")
        self._console.print(f"  {'Extension':<14} {'Files':>6} {'Lines':>10}")
        self._console.print(f"  {'─'*14} {'─'*6} {'─'*10}")
        for entry in stats.sorted_extensions():
            self._console.print(f"  {entry.extension:<14} {entry.files:>6} {entry.lines:>10,}")
        self._console.print(f"  {'─'*14} {'─'*6} {'─'*10}")
        self._console.print(f"  [bold]{'Total':<14} {stats.total_files:>6} {stats.total_lines:>10,}[/bold]")

    def do_exit(self, _arg: str) -> bool:
        self._close_engine(self.engine)
        self._console.print("[dim]Goodbye.[/dim]")
        return True

    do_quit = do_exit
    do_EOF = do_exit

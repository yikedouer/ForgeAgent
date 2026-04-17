"""Interactive REPL — the human-facing terminal interface.

Built on stdlib cmd.Cmd for zero-dependency readline support
(history, arrow keys, Ctrl-C handling). Rich is used solely for
coloured output, not for input.
"""

from __future__ import annotations

import argparse
import cmd
import os
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel

from .. import __version__
from ..core.settings import Settings
from ..core.providers import Provider
from ..core.engine import Engine
from ..context import checkpoint as ckpt
from ..context.compaction import maybe_compact
from ..skills import playbook

console = Console()


# ── Argument parsing ────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forgecc",
        description="ForgeCC — autonomous coding agent for your terminal",
    )
    p.add_argument("-m", "--model", help="Model name (overrides $FORGECC_MODEL)")
    p.add_argument("--base-url", help="API base URL (overrides $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (overrides $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot mode: run a single prompt and exit")
    p.add_argument("-r", "--resume", metavar="SESSION_ID", help="Resume a saved session")
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


# ── Output callbacks ────────────────────────────────────────

def _on_token(tok: str) -> None:
    console.print(tok, end="", highlight=False)


def _on_instrument(name: str, args: dict) -> None:
    brief = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
    console.print(f"\n  [dim]▶ {name}({brief})[/dim]")


def _permission_prompter(tool_name: str, args: dict) -> bool:
    """Interactive confirmation for dangerous operations."""
    try:
        resp = console.input(
            f"  [bold yellow]⚠ Allow dangerous tool '{tool_name}'? (y/N): [/bold yellow]"
        )
        return resp.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ── REPL ────────────────────────────────────────────────────

class ForgeREPL(cmd.Cmd):

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.prompt = "\nYou > "

    def default(self, line: str) -> None:
        """Any non-command input is treated as a user message."""
        if not line.strip():
            return

        # Slash-command skill invocation: /skillname [args]
        if line.startswith("/"):
            self._invoke_skill(line)
            return

        console.print()  # blank line before response
        try:
            answer = self.engine.run(
                line,
                on_token=_on_token,
                on_instrument=_on_instrument,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")
            return
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]")
            return

        # if streaming already printed tokens, just end the line
        if answer:
            console.print()  # newline after streamed output

    def _invoke_skill(self, line: str) -> None:
        """Handle /skillname [args] commands."""
        parts = line[1:].split(" ", 1)
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        pb = playbook.find(name)
        if pb is None:
            available = [p.name for p in playbook.discover()]
            if available:
                console.print(f"[yellow]Unknown skill '{name}'. Available: {', '.join(available)}[/yellow]")
            else:
                console.print(f"[yellow]Unknown skill '{name}'. No skills installed.[/yellow]")
                console.print("[dim]Add skills to .forgecc/skills/<name>/SKILL.md[/dim]")
            return

        if not pb.user_invocable:
            console.print(f"[yellow]Skill '{name}' is auto-only (not user-invocable).[/yellow]")
            return

        console.print(f"  [dim]\u26a1 Invoking skill: {name}[/dim]")

        if pb.mode == "fork":
            # fork mode — run through the skill instrument
            prompt = f'Use the skill instrument to invoke "{name}" with args: {args or "(none)"}'
        else:
            # inline mode — resolve template and send as user message
            prompt = playbook.resolve_template(pb, args)

        try:
            answer = self.engine.run(
                prompt,
                on_token=_on_token,
                on_instrument=_on_instrument,
            )
            if answer:
                console.print()
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")
        except Exception as exc:
            console.print(f"\n[red]Skill error: {exc}[/red]")

    def do_help(self, arg: str) -> None:
        """Show available commands."""
        commands = [
            ("help", "Show this help message"),
            ("save", "Save the current session to disk"),
            ("sessions", "List saved sessions"),
            ("usage", "Show token usage statistics"),
            ("cost", "Estimate token cost for this session"),
            ("skills", "List available skills"),
            ("model [name]", "Show or switch the current model"),
            ("compact", "Manually trigger conversation compaction"),
            ("clear", "Clear the current conversation"),
            ("diff", "Show files modified in this session (git diff)"),
            ("stats", "Count lines of code in current workspace"),
            ("exit / quit", "Exit the REPL"),
        ]
        console.print("\n[bold]Commands[/bold] (prefix with nothing, just type):")
        for name, desc in commands:
            console.print(f"  [cyan]{name:<16}[/cyan] {desc}")
        console.print("\n[bold]Skills[/bold] (prefix with /):\n  /skillname [args]")

    def do_save(self, _arg: str) -> None:
        """Save the current session."""
        path = self.engine.save_checkpoint()
        console.print(f"[green]Session saved → {path}[/green]")

    def do_sessions(self, _arg: str) -> None:
        """List saved sessions."""
        ids = ckpt.list_checkpoints()
        if not ids:
            console.print("[dim]No saved sessions.[/dim]")
        else:
            for sid in ids:
                console.print(f"  {sid}")

    def do_usage(self, _arg: str) -> None:
        """Show token usage."""
        t_in, t_out = self.engine.provider.tokens_used
        console.print(f"  Tokens in: {t_in:,}  |  Tokens out: {t_out:,}")

    def do_skills(self, _arg: str) -> None:
        """List available skills."""
        pbs = playbook.discover()
        if not pbs:
            console.print("[dim]No skills installed. Add to .forgecc/skills/<name>/SKILL.md[/dim]")
            return
        for pb in pbs:
            tag = "inline" if pb.mode == "inline" else "fork"
            inv = "" if pb.user_invocable else " [auto-only]"
            console.print(f"  /{pb.name} [{tag}]{inv} — {pb.description}")

    def do_cost(self, _arg: str) -> None:
        """Estimate token cost for this session."""
        t_in, t_out = self.engine.provider.tokens_used
        # rough pricing (per 1M tokens) — adjustable
        cost_in = t_in * 0.002 / 1000   # $2/M input
        cost_out = t_out * 0.006 / 1000  # $6/M output
        total = cost_in + cost_out
        console.print(f"  Tokens in: {t_in:,} (~${cost_in:.4f})")
        console.print(f"  Tokens out: {t_out:,} (~${cost_out:.4f})")
        console.print(f"  [bold]Estimated total: ${total:.4f}[/bold]")

    def do_model(self, arg: str) -> None:
        """Show or switch the current model."""
        if not arg.strip():
            console.print(f"  Current model: [cyan]{self.engine.settings.model}[/cyan]")
            console.print(f"  Base URL: {self.engine.settings.base_url}")
            return
        new_model = arg.strip()
        self.engine.settings = self.engine.settings.replace(model=new_model)
        self.engine.provider._model = new_model
        console.print(f"  [green]Switched to model: {new_model}[/green]")

    def do_compact(self, _arg: str) -> None:
        """Manually trigger conversation compaction."""
        before = len(self.engine.transcript)
        compacted = maybe_compact(
            self.engine.transcript,
            self.engine.settings.context_budget,
            self.engine.provider,
        )
        after = len(self.engine.transcript)
        if compacted:
            console.print(f"  [green]Compacted: {before} → {after} messages[/green]")
        else:
            console.print("  [dim]No compaction needed.[/dim]")

    def do_clear(self, _arg: str) -> None:
        """Clear the current conversation."""
        self.engine.transcript.clear()
        self.engine._round = 0
        console.print("  [green]Conversation cleared.[/green]")

    def do_diff(self, _arg: str) -> None:
        """Show files modified since session start (git diff)."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True,
                cwd=self.engine.settings.workspace,
            )
            output = result.stdout.strip()
            if output:
                console.print(output)
            else:
                console.print("  [dim]No changes detected (git diff empty).[/dim]")
        except Exception as exc:
            console.print(f"  [red]git diff failed: {exc}[/red]")

    def do_stats(self, _arg: str) -> None:
        """Count lines of code in the current workspace."""
        workspace = self.engine.settings.workspace
        skip_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
            ".eggs", "*.egg-info", ".hatch",
        }
        counts: dict[str, int] = {}   # ext -> lines
        file_counts: dict[str, int] = {}  # ext -> files
        total_lines = 0
        total_files = 0

        for root, dirs, files in os.walk(workspace):
            # prune skipped directories in-place
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
            for fname in files:
                ext = os.path.splitext(fname)[1] or fname  # no ext → use filename
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        n = sum(1 for _ in f)
                except (OSError, UnicodeDecodeError):
                    continue
                counts[ext] = counts.get(ext, 0) + n
                file_counts[ext] = file_counts.get(ext, 0) + 1
                total_lines += n
                total_files += 1

        if not counts:
            console.print("  [dim]No files found.[/dim]")
            return

        # sort by line count descending
        sorted_exts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        console.print(f"\n  [bold]Workspace:[/bold] {workspace}\n")
        console.print(f"  {'Extension':<14} {'Files':>6} {'Lines':>10}")
        console.print(f"  {'─'*14} {'─'*6} {'─'*10}")
        for ext, lines in sorted_exts:
            console.print(f"  {ext:<14} {file_counts[ext]:>6} {lines:>10,}")
        console.print(f"  {'─'*14} {'─'*6} {'─'*10}")
        console.print(f"  [bold]{'Total':<14} {total_files:>6} {total_lines:>10,}[/bold]")

    def do_exit(self, _arg: str) -> bool:
        """Exit the REPL."""
        console.print("[dim]Goodbye.[/dim]")
        return True

    do_quit = do_exit
    do_EOF = do_exit

    def emptyline(self) -> None:
        pass  # don't repeat last command on blank input


# ── Main entry point ────────────────────────────────────────

def main() -> None:
    args = _build_parser().parse_args()
    settings = Settings.resolve()

    # CLI args override env
    overrides: dict = {}
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    if overrides:
        settings = settings.replace(**overrides)

    if not settings.api_key:
        console.print("[red bold]No API key.[/red bold] Set OPENAI_API_KEY or use --api-key.")
        sys.exit(1)

    provider = Provider(settings)
    engine = Engine(settings, provider)

    # register interactive prompter for PROMPT permission mode
    engine.enforcer.set_prompter(_permission_prompter)

    # resume session?
    if args.resume:
        try:
            engine.restore_checkpoint(args.resume)
            console.print(f"[green]Resumed session {args.resume}[/green]")
        except FileNotFoundError:
            console.print(f"[red]Session not found: {args.resume}[/red]")
            sys.exit(1)

    # one-shot mode
    if args.prompt:
        answer = engine.run(args.prompt, on_token=_on_token, on_instrument=_on_instrument)
        if answer:
            console.print()
        return

    # interactive REPL
    console.print(Panel.fit(
        f"[bold]ForgeCC[/bold] v{__version__}  •  model: {settings.model}",
        border_style="blue",
    ))
    console.print("[dim]Type a task, or 'help' for commands. Skills: /skillname[/dim]")

    repl = ForgeREPL(engine)
    try:
        repl.cmdloop()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")

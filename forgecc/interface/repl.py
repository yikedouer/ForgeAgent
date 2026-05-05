"""交互式 REPL——面向用户的终端界面。"""

from __future__ import annotations

import argparse
import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel

from .. import __version__
from ..core.settings import Settings
from ..core.providers import Provider
from ..core.engine import Engine
from ..core.permissions import PermissionMode
from ..context import checkpoint as ckpt
from ..core.log import get_logger
from .export_command import run_export_command
from .one_shot import close_engine, run_prompt_once
from .plan_approval import build_plan_approval_fn
from .repl_commands import ForgeReplCommandMixin
from .cli_startup import (
    CliStartupError,
    apply_cli_settings_overrides,
    normalize_resume_id,
    validate_prompt_options,
)

log = get_logger(__name__)
console = Console()

COMMANDS = (
    "help",
    "save",
    "sessions",
    "usage",
    "cost",
    "skills",
    "plan",
    "model",
    "compact",
    "clear",
    "memory",
    "remember",
    "diff",
    "export",
    "stats",
    "exit",
    "quit",
)


# ── 参数解析 ──────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forgecc",
        description="ForgeCC — autonomous coding agent for your terminal",
    )
    p.add_argument("-m", "--model", help="Model name (overrides $FORGECC_MODEL)")
    p.add_argument("--base-url", help="API base URL (overrides $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (overrides $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot mode: run a single prompt and exit")
    p.add_argument(
        "--output-format",
        choices=("text", "json", "jsonl"),
        default="text",
        help="Output format for one-shot mode or export",
    )
    p.add_argument("-r", "--resume", metavar="SESSION_ID", help="Resume a saved session")
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("command", nargs="?", help="Command: export")
    p.add_argument("command_args", nargs="*", help="Arguments for command")
    return p


# ── 输出回调 ──────────────────────────────────────────────

def _on_token(tok: str) -> None:
    console.print(tok, end="", highlight=False)


def _on_tool(name: str, args: object) -> None:
    if isinstance(args, dict):
        brief = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
    else:
        brief = f"<invalid args: {type(args).__name__}>"
    console.print(f"\n  [dim]▶ {name}({brief})[/dim]")


def _permission_prompter(tool_name: str, args: dict) -> bool:
    """危险操作的交互确认。"""
    try:
        resp = console.input(
            f"  [bold yellow]⚠ Allow dangerous tool '{tool_name}'? (y/N): [/bold yellow]"
        )
        return resp.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _close_engine(engine: object) -> None:
    close_engine(engine)


# ── REPL ────────────────────────────────────────────────────

class ForgeCompleter(Completer):
    def get_completions(self, document, _complete_event):
        text = document.text_before_cursor.lstrip()
        if " " in text or text.startswith("/"):
            return
        for name in COMMANDS:
            if name.startswith(text):
                yield Completion(name, start_position=-len(text))


class ForgeREPL(ForgeReplCommandMixin):

    def __init__(self, engine: Engine):
        self.engine = engine
        self._console = console
        self._on_token = _on_token
        self._on_tool = _on_tool
        self._close_engine = _close_engine
        self.prompt = "\nYou > "
        self._session = PromptSession(
            history=InMemoryHistory(),
            completer=ForgeCompleter(),
        )
        self._setup_plan_approval()

    def _setup_plan_approval(self) -> None:
        """注册交互式计划审批回调。"""
        self.engine.set_plan_approval_fn(build_plan_approval_fn(console))

    def default(self, line: str) -> None:
        """任何非命令输入都作为用户消息处理。"""
        if not line.strip():
            return

        handled, should_exit = self._dispatch_command(line)
        if handled:
            return True if should_exit else None

        # 斜杠命令技能调用：/skillname [args]
        if line.startswith("/"):
            if self._invoke_slash_builtin(line):
                return
            self._invoke_skill(line)
            return

        log.info("REPL 将用户输入交给 Engine: %s", line[:100])
        console.print()  # blank line before response
        try:
            answer = self.engine.run(
                line,
                on_token=_on_token,
                on_tool=_on_tool,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")
            return
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]")
            return

        # 如果流式输出已打印 token，只需结束行
        if answer:
            console.print()  # newline after streamed output

    def emptyline(self) -> None:
        pass  # 空行输入时不重复上一条命令

    def _dispatch_command(self, line: str) -> tuple[bool, bool]:
        name, _, arg = line.strip().partition(" ")
        command = getattr(self, f"do_{name}", None)
        if command is None:
            return False, False
        result = command(arg)
        return True, result is True

    def run(self) -> None:
        while True:
            try:
                line = self._session.prompt(self.prompt)
            except KeyboardInterrupt:
                console.print("\n[yellow]interrupted[/yellow]")
                continue
            except EOFError:
                self.do_exit("")
                return
            if self.default(line) is True:
                return


# ── 主入口 ────────────────────────────────────────────────

def main() -> None:
    args = _build_parser().parse_args()
    if args.command is not None:
        if args.command == "export":
            run_export_command(
                args.command_args,
                output_format=args.output_format,
                output_console=console,
            )
            return
        console.print(f"[red]Unknown command: {args.command}[/red]")
        sys.exit(2)

    try:
        args.resume = normalize_resume_id(args.resume, ckpt.latest_checkpoint)
    except CliStartupError as exc:
        console.print(f"[red]{exc.message}[/red]")
        sys.exit(exc.exit_code)
    settings = Settings.resolve()

    # checkpoint 模型提供 resume 默认值；显式 CLI 参数仍保持最高优先级
    if args.resume:
        try:
            resume_ckpt = ckpt.load(args.resume)
        except FileNotFoundError:
            console.print(f"[red]Session not found: {args.resume}[/red]")
            sys.exit(1)
        if resume_ckpt.model and not args.model and resume_ckpt.model != settings.model:
            settings = settings.for_model(resume_ckpt.model)

    try:
        settings = apply_cli_settings_overrides(
            settings,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
        )
        validate_prompt_options(args.prompt, args.output_format)
    except CliStartupError as exc:
        console.print(f"[red]{exc.message}[/red]")
        sys.exit(exc.exit_code)

    if not settings.api_key:
        console.print("[red bold]No API key.[/red bold] Set OPENAI_API_KEY or use --api-key.")
        sys.exit(1)

    provider = Provider(settings)
    engine = Engine(settings, provider)
    log.info("ForgeCC v%s 启动  model=%s  workspace=%s",
             __version__, settings.model, settings.workspace)

    # 为 PROMPT 权限模式注册交互式确认器
    engine.enforcer.set_prompter(_permission_prompter)

    # 恢复会话？
    if args.resume:
        try:
            engine.restore_checkpoint(args.resume, restore_model=False)
            console.print(f"[green]Resumed session {args.resume}[/green]")
        except FileNotFoundError:
            console.print(f"[red]Session not found: {args.resume}[/red]")
            sys.exit(1)

    # 单次模式
    if args.prompt:
        run_prompt_once(
            engine,
            args.prompt,
            output_format=args.output_format,
            output_console=console,
            on_token=_on_token,
            on_tool=_on_tool,
        )
        return

    # 交互式 REPL
    console.print(Panel.fit(
        f"[bold]ForgeCC[/bold] v{__version__}  •  model: {settings.model}",
        border_style="blue",
    ))
    console.print("[dim]Type a task, or 'help' for commands. Skills: /skillname[/dim]")

    repl = ForgeREPL(engine)
    try:
        repl.run()
    except KeyboardInterrupt:
        _close_engine(engine)
        console.print("\n[dim]Goodbye.[/dim]")

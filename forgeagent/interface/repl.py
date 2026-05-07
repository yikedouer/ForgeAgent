"""交互式 REPL——面向用户的终端界面。"""

from __future__ import annotations

import argparse
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel

from .. import __version__
from ..core.settings import Settings
from ..core.providers import Provider
from ..core.engine import Engine
from ..core.permissions import PermissionMode
from ..context import checkpoint as ckpt
from ..context.compaction_tokens import conversation_tokens
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

STATUS_STYLE = Style.from_dict({
    "bottom-toolbar": "noreverse bg:#202020 #8a8a8a",
    "status.label": "bg:#202020 #8ab4f8",
    "status.value": "bg:#202020 #c9d1d9",
    "status.sep": "bg:#202020 #4b5563",
})


# ── 参数解析 ──────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forgeagent",
        description="ForgeAgent — autonomous coding agent for your terminal",
    )
    p.add_argument("-m", "--model", help="Model name (overrides $MODEL)")
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


def _preview_suffix(value: object, limit: int = 120) -> str:
    if not value:
        return ""
    text = str(value).replace("\n", "\\n")
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    return f": {text}"


def _timeline_tool_action(name: str, args: object) -> tuple[str, str]:
    if not isinstance(args, dict):
        return "Tool", name
    path = args.get("path") or args.get("file_path") or args.get("root")
    if name == "read_file":
        return "Explored", f"Read {path or 'file'}"
    if name == "glob_search":
        return "Explored", f"Search {args.get('pattern') or '*'}"
    if name == "grep_search":
        return "Explored", f"Search {args.get('pattern') or 'pattern'}"
    if name == "write_file":
        return "Edited", f"Write {path or 'file'}"
    if name == "edit_file":
        return "Edited", f"Edit {path or 'file'}"
    if name == "shell":
        return "Ran", str(args.get("command") or "").strip() or "shell command"
    if name == "agent":
        agent_type = args.get("type") or "general"
        description = args.get("description") or "task"
        return "Agent", f"{agent_type}: {description}"
    if name == "team":
        agents = args.get("agents")
        count = len(agents) if isinstance(agents, list) else 0
        return "Agents", f"{count} tasks"
    if name == "enter_plan_mode":
        return "Plan", "Entered plan mode"
    if name == "exit_plan_mode":
        return "Plan", "Ready for approval"
    return "Tool", name


def _timeline_tool_result(payload: dict) -> str:
    ok = bool(payload.get("ok", True))
    preview = str(payload.get("preview") or "")
    if not ok:
        return f"  [red]failed{_preview_suffix(preview)}[/red]"
    return ""


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


def _status_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ── REPL ────────────────────────────────────────────────────

class ForgeCompleter(Completer):
    def get_completions(self, document, _complete_event):
        text = document.text_before_cursor.lstrip()
        if " " in text or not text.startswith("/"):
            return
        prefix = text[1:]
        for name in COMMANDS:
            if name.startswith(prefix):
                yield Completion(f"/{name}", start_position=-len(text))


class ForgeREPL(ForgeReplCommandMixin):

    def __init__(self, engine: Engine):
        self.engine = engine
        self._console = console
        self._on_token = _on_token
        self._on_tool = self._handle_tool
        self._on_event = self._handle_event
        self._close_engine = _close_engine
        self._last_timeline_group = ""
        self.prompt = "\n› "
        self._session = PromptSession(
            history=InMemoryHistory(),
            completer=ForgeCompleter(),
            bottom_toolbar=self._status_bar,
            style=STATUS_STYLE,
        )
        self._setup_plan_approval()

    def _setup_plan_approval(self) -> None:
        """注册交互式计划审批回调。"""
        self.engine.set_plan_approval_fn(build_plan_approval_fn(console))

    def _mode_label(self) -> str:
        mode = getattr(self.engine.enforcer, "mode", None)
        if mode == PermissionMode.PLAN:
            return "plan"
        return "normal"

    def _status_line(self) -> str:
        fallback = getattr(getattr(self.engine, "provider", None), "tokens_used", (0, 0))
        if not isinstance(fallback, tuple) or len(fallback) != 2:
            fallback = (0, 0)
        tokens_in = _status_int(getattr(self.engine, "_total_input_tokens", fallback[0]))
        tokens_out = _status_int(getattr(self.engine, "_total_output_tokens", fallback[1]))
        settings = getattr(self.engine, "settings", None)
        budget = _status_int(getattr(settings, "context_budget", 0))
        context_tokens = conversation_tokens(getattr(self.engine, "transcript", []))
        context_pct = context_tokens / budget * 100 if budget else 0
        enforcer = getattr(self.engine, "enforcer", None)
        mode = getattr(enforcer, "mode", None)
        permission = getattr(mode, "value", str(mode or "unknown"))
        model = getattr(settings, "model", "unknown")
        return (
            f"mode: {self._mode_label()} | "
            f"perm: {permission} | "
            f"model: {model} | "
            f"usage: {tokens_in:,} in / {tokens_out:,} out | "
            f"ctx: {context_pct:.0f}%"
        )

    def _status_bar(self) -> list[tuple[str, str]]:
        parts = self._status_line().split(" | ")
        fragments: list[tuple[str, str]] = []
        for index, part in enumerate(parts):
            label, sep, value = part.partition(": ")
            if sep:
                fragments.append(("class:status.label", label))
                fragments.append(("class:status.sep", ": "))
                fragments.append(("class:status.value", value))
            else:
                fragments.append(("class:status.value", part))
            if index < len(parts) - 1:
                fragments.append(("class:status.sep", " | "))
        return fragments

    def default(self, line: str) -> None:
        """任何非命令输入都作为用户消息处理。"""
        if not line.strip():
            return

        handled, should_exit = self._dispatch_command(line)
        if handled:
            return True if should_exit else None

        stripped = line.lstrip()
        # 斜杠技能调用：/skillname [args]
        if stripped.startswith("/"):
            self._invoke_skill(stripped)
            return

        log.info("REPL 将用户输入交给 Engine: %s", line[:100])
        self._last_timeline_group = ""
        console.print()  # blank line before response
        try:
            answer = self.engine.run(
                line,
                on_token=_on_token,
                on_tool=self._on_tool,
                on_event=self._on_event,
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
        stripped = line.strip()
        if not stripped.startswith("/"):
            return False, False
        parts = stripped[1:].lstrip().split(maxsplit=1)
        name = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        if not name:
            return False, False
        command = getattr(self, f"do_{name}", None)
        if command is None:
            return False, False
        result = command(arg)
        return True, result is True

    def _handle_tool(self, name: str, args: object) -> None:
        group, detail = _timeline_tool_action(name, args)
        same_group = group == self._last_timeline_group and group == "Explored"
        self._last_timeline_group = group
        if same_group:
            self._console.print(f"  └ {detail}")
        else:
            self._console.print(f"\n• [bold]{group}[/bold]\n  └ {detail}")

    def _handle_event(self, kind: str, payload: dict) -> None:
        if kind in {"round_start", "llm_response"}:
            return
        if kind in {"tool_result", "plan_tool_result"}:
            result = _timeline_tool_result(payload)
            if result:
                self._console.print(result)
            return
        self._console.print(f"  [dim]• {kind}: {payload}[/dim]")

    def run(self) -> None:
        while True:
            try:
                line = self._session.prompt(self.prompt)
            except KeyboardInterrupt:
                self.do_exit("")
                return
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
    log.info("ForgeAgent v%s 启动  model=%s  workspace=%s",
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

    # Normal terminal buffer: native scrollback, copy, and search remain available.
    console.print(Panel.fit(
        f"[bold]ForgeAgent[/bold] v{__version__}  •  model: {settings.model}",
        border_style="blue",
    ))
    console.print("[dim]Type a task, or /help for commands. Skills: /skillname[/dim]")

    repl = ForgeREPL(engine)
    try:
        repl.run()
    except KeyboardInterrupt:
        _close_engine(engine)
        console.print("\n[dim]Goodbye.[/dim]")

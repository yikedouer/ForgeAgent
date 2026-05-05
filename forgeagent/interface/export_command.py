"""Offline checkpoint export command implementation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console

from ..context import checkpoint as ckpt
from .export import render_events_jsonl, render_transcript_markdown

console = Console()


def run_export_command(
    args: list[str],
    *,
    output_format: str = "text",
    output_console: Console | None = None,
) -> None:
    """Export the latest checkpoint as Markdown, JSON, or JSONL events."""
    printer = output_console or console
    if len(args) > 1:
        printer.print("[red]Usage: forgeagent export [file][/red]")
        sys.exit(2)

    latest = ckpt.latest_checkpoint()
    if latest is None:
        printer.print("[red]No saved sessions.[/red]")
        sys.exit(1)

    if output_format == "jsonl":
        event_stream = render_events_jsonl(ckpt.load_events(latest))
        if args:
            output = Path(args[0]).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(event_stream, encoding="utf-8")
            printer.print(f"  [green]Exported events → {output}[/green]")
            return
        printer.print(event_stream, end="")
        return

    checkpoint = ckpt.load(latest)
    markdown = render_transcript_markdown(
        checkpoint.session_id,
        checkpoint.messages,
    )
    if args:
        output = Path(args[0]).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        if output_format == "json":
            printer.print(json.dumps(
                {
                    "kind": "export",
                    "file": str(output),
                    "session_id": checkpoint.session_id,
                    "messages": len(checkpoint.messages),
                },
                ensure_ascii=False,
            ))
            return
        printer.print(f"  [green]Exported conversation → {output}[/green]")
        return

    if output_format == "json":
        printer.print(json.dumps(
            {
                "kind": "export",
                "file": None,
                "session_id": checkpoint.session_id,
                "messages": len(checkpoint.messages),
                "markdown": markdown,
            },
            ensure_ascii=False,
        ))
        return

    printer.print(markdown, end="")

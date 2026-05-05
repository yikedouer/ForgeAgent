import json

import pytest

from forgecc.context.checkpoint import Checkpoint
from forgecc.interface.export_command import run_export_command


def test_run_export_command_writes_latest_checkpoint_markdown(tmp_path, monkeypatch) -> None:
    output = tmp_path / "latest.md"
    printed: list[str] = []

    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.latest_checkpoint",
        lambda: "latest_session",
    )
    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.load",
        lambda session_id: Checkpoint(
            session_id=session_id,
            messages=[
                {"role": "user", "content": "offline export"},
                {"role": "assistant", "content": "ready"},
            ],
            model="qwen3.6-plus",
        ),
    )
    monkeypatch.setattr(
        "forgecc.interface.export_command.console.print",
        lambda *args, **kwargs: printed.append(args[0] if args else ""),
    )

    run_export_command([str(output)])

    markdown = output.read_text(encoding="utf-8")
    assert "- **Session**: `latest_session`" in markdown
    assert "offline export" in markdown
    assert "ready" in markdown
    assert str(output) in printed[-1]


def test_run_export_command_can_emit_json_output(tmp_path, monkeypatch) -> None:
    output = tmp_path / "latest.md"
    printed: list[str] = []

    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.latest_checkpoint",
        lambda: "latest_session",
    )
    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.load",
        lambda session_id: Checkpoint(
            session_id=session_id,
            messages=[{"role": "user", "content": "export json"}],
            model="qwen3.6-plus",
        ),
    )
    monkeypatch.setattr(
        "forgecc.interface.export_command.console.print",
        lambda *args, **kwargs: printed.append(args[0] if args else ""),
    )

    run_export_command([str(output)], output_format="json")

    assert json.loads(printed[-1]) == {
        "kind": "export",
        "file": str(output),
        "session_id": "latest_session",
        "messages": 1,
    }
    assert "export json" in output.read_text(encoding="utf-8")


def test_run_export_command_can_write_jsonl_event_stream(tmp_path, monkeypatch) -> None:
    output = tmp_path / "latest.jsonl"
    events = [
        {"type": "checkpoint", "session_id": "latest_session", "messages": 1},
        {
            "type": "message",
            "session_id": "latest_session",
            "index": 0,
            "message": {"role": "user", "content": "event export"},
        },
    ]

    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.latest_checkpoint",
        lambda: "latest_session",
    )
    monkeypatch.setattr(
        "forgecc.interface.export_command.ckpt.load_events",
        lambda session_id: events,
    )

    run_export_command([str(output)], output_format="jsonl")

    lines = output.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == events


def test_run_export_command_rejects_too_many_args() -> None:
    with pytest.raises(SystemExit) as exc:
        run_export_command(["one", "two"])

    assert exc.value.code == 2

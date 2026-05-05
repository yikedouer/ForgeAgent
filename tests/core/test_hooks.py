"""test_hooks.py — runtime hook registry tests."""

from __future__ import annotations

from forgeagent.core.hooks import clear_hooks, emit_hook, load_hook_file, register_hook


def test_emit_hook_calls_registered_handlers_in_order():
    clear_hooks()
    seen: list[tuple[str, dict]] = []

    def first(event: str, payload: dict) -> None:
        payload["mutated"] = True
        seen.append((event, payload))

    def second(event: str, payload: dict) -> None:
        seen.append((event, payload))

    register_hook("tool.before", first)
    register_hook("tool.before", second)

    try:
        results = emit_hook("tool.before", {"name": "read_file"})
    finally:
        clear_hooks()

    assert [entry[0] for entry in seen] == ["tool.before", "tool.before"]
    assert seen[0][1] == {"name": "read_file", "mutated": True}
    assert seen[1][1] == {"name": "read_file"}
    assert [result.ok for result in results] == [True, True]


def test_load_hook_file_registers_handlers(tmp_path):
    clear_hooks()
    hook_file = tmp_path / "audit_hook.py"
    audit_file = tmp_path / "audit.log"
    hook_file.write_text(
        "\n".join(
            [
                f"AUDIT_FILE = {str(audit_file)!r}",
                "def register(register_hook):",
                "    def capture(event, payload):",
                "        with open(AUDIT_FILE, 'a', encoding='utf-8') as handle:",
                "            handle.write(f\"{event}:{payload['name']}\\n\")",
                "    register_hook('tool.after', capture)",
            ]
        ),
        encoding="utf-8",
    )

    try:
        loaded = load_hook_file(hook_file)
        emit_hook("tool.after", {"name": "read_file"})
    finally:
        clear_hooks()

    assert loaded == hook_file
    assert audit_file.read_text(encoding="utf-8") == "tool.after:read_file\n"

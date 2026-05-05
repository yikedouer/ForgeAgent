"""Runtime hook registry for lightweight extension points."""

from __future__ import annotations

import copy
import importlib.util
from dataclasses import dataclass
from typing import Callable
from pathlib import Path


HookHandler = Callable[[str, dict], None]


@dataclass(frozen=True)
class HookResult:
    event: str
    ok: bool
    error: str = ""


_HOOKS: dict[str, list[HookHandler]] = {}


def register_hook(event: str, handler: HookHandler) -> None:
    """Register a handler for an event name."""
    if not isinstance(event, str) or not event.strip():
        raise ValueError("invalid hook event: expected non-empty string")
    if not callable(handler):
        raise ValueError("invalid hook handler: expected callable")
    _HOOKS.setdefault(event, []).append(handler)


def clear_hooks(event: str | None = None) -> None:
    """Clear all hooks or only handlers for one event."""
    if event is None:
        _HOOKS.clear()
        return
    _HOOKS.pop(event, None)


def load_hook_file(path: str | Path) -> Path:
    """Load a Python hook file and call its register(register_hook) entrypoint."""
    hook_path = Path(path).expanduser()
    if not hook_path.is_file():
        raise FileNotFoundError(str(hook_path))
    module_name = f"forgecc_user_hook_{abs(hash(str(hook_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, hook_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Invalid hook file: {hook_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if not callable(register):
        raise ValueError(f"Hook file must define register(register_hook): {hook_path}")
    register(register_hook)
    return hook_path


def emit_hook(event: str, payload: dict | None = None) -> list[HookResult]:
    """Emit an event to registered handlers.

    Each handler receives an isolated payload copy so mutation cannot leak
    between extensions or back into the caller.
    """
    if not isinstance(event, str) or not event.strip():
        raise ValueError("invalid hook event: expected non-empty string")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("invalid hook payload: expected object")

    results: list[HookResult] = []
    for handler in list(_HOOKS.get(event, [])):
        try:
            handler(event, copy.deepcopy(payload or {}))
            results.append(HookResult(event=event, ok=True))
        except Exception as exc:
            results.append(HookResult(event=event, ok=False, error=str(exc)))
    return results

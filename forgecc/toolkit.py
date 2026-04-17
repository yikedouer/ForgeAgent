"""Instrument registry — decorator-driven tool management.

Every instrument is a plain function decorated with @instrument(). The
decorator collects metadata (name, description, parameter schema) and
registers the function in a global catalog. The engine queries this
catalog at runtime to build tool declarations for the LLM and to
dispatch calls.

This is intentionally *not* class-based. A tool is just a function
with metadata attached — closer to the declarative spirit of the
original architecture.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .core.permissions import PermissionEnforcer


# ── Instrument descriptor ───────────────────────────────────

@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    description: str
    parameters: dict          # JSON-Schema fragment
    fn: Callable[..., str]    # the actual implementation
    readonly: bool = False    # safe for concurrent execution
    risk_level: str = "write" # 'read' / 'write' / 'danger'


# ── Global catalog ──────────────────────────────────────────

_CATALOG: dict[str, InstrumentSpec] = {}


def instrument(
    name: str,
    description: str,
    parameters: dict,
    *,
    readonly: bool = False,
    risk_level: str = "write",
) -> Callable:
    """Decorator that registers a function as an instrument."""
    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        spec = InstrumentSpec(
            name=name,
            description=description,
            parameters=parameters,
            fn=fn,
            readonly=readonly,
            risk_level=risk_level,
        )
        _CATALOG[name] = spec
        return fn
    return decorator


def catalog() -> dict[str, InstrumentSpec]:
    """Return the full instrument catalog (read-only view)."""
    return dict(_CATALOG)


def lookup(name: str) -> InstrumentSpec | None:
    return _CATALOG.get(name)


def schemas() -> list[dict]:
    """Build the list of function schemas the LLM expects."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in _CATALOG.values()
    ]


# ── Permission enforcer (set by engine at startup) ────────

_enforcer: PermissionEnforcer | None = None


def set_enforcer(enforcer: PermissionEnforcer) -> None:
    global _enforcer
    _enforcer = enforcer


# ── Execution helpers ───────────────────────────────────────

@dataclass
class InstrumentResult:
    call_id: str
    name: str
    output: str
    ok: bool = True


def run_one(call_id: str, name: str, args: dict) -> InstrumentResult:
    """Execute a single instrument by name."""
    spec = lookup(name)
    if spec is None:
        return InstrumentResult(call_id=call_id, name=name,
                                output=f"Unknown instrument: {name}", ok=False)

    # permission check
    if _enforcer is not None:
        denial = _enforcer.check(name, spec.risk_level, args)
        if denial:
            return InstrumentResult(call_id=call_id, name=name,
                                    output=denial, ok=False)

    try:
        output = spec.fn(**args)
        return InstrumentResult(call_id=call_id, name=name, output=output)
    except Exception as exc:
        return InstrumentResult(call_id=call_id, name=name,
                                output=f"Error: {exc}", ok=False)


def run_batch(calls: list[tuple[str, str, dict]]) -> list[InstrumentResult]:
    """Execute multiple instrument calls, parallelising read-only ones.

    Each element is (call_id, instrument_name, args).
    Preserves order of the input list.
    """
    if not calls:
        return []

    # if ALL calls are readonly, run them concurrently
    all_readonly = all(
        (s := lookup(name)) is not None and s.readonly
        for _, name, _ in calls
    )

    if all_readonly and len(calls) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = {
                pool.submit(run_one, cid, name, args): i
                for i, (cid, name, args) in enumerate(calls)
            }
            results = [None] * len(calls)
            for fut in concurrent.futures.as_completed(futures):
                results[futures[fut]] = fut.result()
            return results  # type: ignore[return-value]

    # otherwise execute sequentially (writes must not overlap)
    return [run_one(cid, name, args) for cid, name, args in calls]

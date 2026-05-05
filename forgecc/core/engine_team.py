"""Team sub-agent execution and result aggregation helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable


def spec_description(spec: object) -> str:
    if isinstance(spec, dict) and isinstance(spec.get("description"), str):
        return spec["description"]
    return ""


def collect_team_results(
    agent_specs: list[dict],
    future_map: dict[object, int],
    *,
    completed_futures: Iterable[object] | None = None,
) -> list[dict]:
    ordered: list[dict | None] = [None] * len(agent_specs)
    futures = completed_futures if completed_futures is not None else as_completed(future_map)
    for future in futures:
        idx = future_map[future]
        try:
            ordered[idx] = future.result()
        except Exception as exc:
            ordered[idx] = {
                "description": spec_description(agent_specs[idx]),
                "result": f"(thread error: {exc})",
                "tokens_in": 0,
                "tokens_out": 0,
            }
    return [result for result in ordered if result is not None]


def team_token_totals(results: list[dict]) -> tuple[int, int]:
    return (
        sum(result["tokens_in"] for result in results),
        sum(result["tokens_out"] for result in results),
    )


RunOneFn = Callable[..., dict]


def run_sub_agent_team(
    agent_specs: list[dict],
    *,
    run_one: RunOneFn,
    max_workers: int = 4,
) -> list[dict]:
    """Run sub-agent specs in parallel and preserve original spec order."""
    if not agent_specs:
        return []

    def _run_spec(spec: dict) -> dict:
        return run_one(
            agent_type=spec.get("type", "general"),
            description=spec.get("description", "sub-agent"),
            prompt=spec.get("prompt", ""),
            model=spec.get("model"),
        )

    with ThreadPoolExecutor(
        max_workers=min(len(agent_specs), max_workers),
        thread_name_prefix="forgecc-agent",
    ) as pool:
        future_map = {
            pool.submit(_run_spec, spec): i
            for i, spec in enumerate(agent_specs)
        }
        return collect_team_results(agent_specs, future_map)

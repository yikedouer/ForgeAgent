from __future__ import annotations

from forgecc.core.subagent_runtime import (
    collect_team_results,
    run_sub_agent_team,
    team_token_totals,
)


class FakeFuture:
    def __init__(self, value=None, exc: Exception | None = None):
        self.value = value
        self.exc = exc

    def result(self):
        if self.exc:
            raise self.exc
        return self.value


def test_collect_team_results_preserves_original_spec_order():
    first = FakeFuture({"description": "first", "tokens_in": 1, "tokens_out": 2})
    second = FakeFuture({"description": "second", "tokens_in": 3, "tokens_out": 4})
    future_map = {first: 0, second: 1}

    results = collect_team_results(
        [{"description": "first"}, {"description": "second"}],
        future_map,
        completed_futures=(second, first),
    )

    assert [result["description"] for result in results] == ["first", "second"]


def test_collect_team_results_turns_future_exceptions_into_result_rows():
    failed = FakeFuture(exc=RuntimeError("boom"))

    results = collect_team_results(
        [{"description": "broken"}],
        {failed: 0},
        completed_futures=(failed,),
    )

    assert results == [{
        "description": "broken",
        "result": "(thread error: boom)",
        "tokens_in": 0,
        "tokens_out": 0,
    }]


def test_team_token_totals_sum_result_usage():
    assert team_token_totals([
        {"tokens_in": 1, "tokens_out": 2},
        {"tokens_in": 3, "tokens_out": 4},
    ]) == (4, 6)


def test_run_sub_agent_team_runs_specs_and_returns_ordered_results():
    calls = []

    results = run_sub_agent_team(
        agent_specs=[
            {"type": "explore", "description": "first", "prompt": "one", "model": "m1"},
            {"description": "second", "prompt": "two"},
        ],
        max_workers=2,
        run_one=lambda **kwargs: calls.append(kwargs) or {
            "description": kwargs["description"],
            "result": kwargs["prompt"].upper(),
            "tokens_in": 1,
            "tokens_out": 2,
        },
    )

    call_by_description = {call["description"]: call for call in calls}
    assert call_by_description["first"]["agent_type"] == "explore"
    assert call_by_description["second"]["agent_type"] == "general"
    assert call_by_description["first"]["model"] == "m1"
    assert call_by_description["second"]["model"] is None
    assert results == [
        {"description": "first", "result": "ONE", "tokens_in": 1, "tokens_out": 2},
        {"description": "second", "result": "TWO", "tokens_in": 1, "tokens_out": 2},
    ]


def test_run_sub_agent_team_returns_empty_without_creating_workers():
    calls = []

    assert run_sub_agent_team(
        [],
        run_one=lambda **kwargs: calls.append(kwargs),
    ) == []
    assert calls == []

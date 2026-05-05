from unittest.mock import MagicMock

from forgecc.core.engine_session import run_manual_compaction


def test_run_manual_compaction_reports_before_after_stats() -> None:
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "reply"},
    ]
    provider = MagicMock()
    result = MagicMock()
    result.performed = True
    result.collapse = object()

    def fake_compact(*args, **kwargs):
        messages.append({"role": "assistant", "content": "summary"})
        return result

    report = run_manual_compaction(
        messages,
        budget=1000,
        provider=provider,
        session_id="s1",
        collapse_state=None,
        failure_count=[0],
        compact=fake_compact,
    )

    assert report.result is result
    assert report.before_messages == 2
    assert report.after_messages == 3
    assert report.before_tokens > 0
    assert report.after_tokens >= report.before_tokens
    assert report.context_budget == 1000

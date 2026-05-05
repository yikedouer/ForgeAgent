from __future__ import annotations

from pathlib import Path

from forgecc.core.subagent_runtime import (
    AgentRunRecord,
    begin_agent_run_record,
    finish_agent_run_record,
)


def test_begin_agent_run_record_creates_named_run():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return Path("/tmp/run.md"), Path("/tmp/run.json")

    record = begin_agent_run_record(
        workspace="/workspace",
        agent_id="agent-1",
        description="Review Code!",
        subagent_type="review",
        model="qwen3.6-plus",
        prompt="inspect",
        create=create,
    )

    assert record == AgentRunRecord(Path("/tmp/run.md"), Path("/tmp/run.json"))
    assert captured["workspace"] == "/workspace"
    assert captured["name"] == "review-code!"
    assert captured["description"] == "Review Code!"
    assert captured["subagent_type"] == "review"
    assert captured["model"] == "qwen3.6-plus"
    assert captured["prompt"] == "inspect"


def test_begin_agent_run_record_returns_none_when_create_fails():
    warnings = []

    def create(**kwargs):
        raise RuntimeError("disk full")

    record = begin_agent_run_record(
        workspace="/workspace",
        agent_id="agent-1",
        description="Review Code!",
        subagent_type="review",
        model="qwen3.6-plus",
        prompt="inspect",
        create=create,
        warn=warnings.append,
    )

    assert record is None
    assert warnings == ["创建子 Agent 运行记录失败: disk full"]


def test_finish_agent_run_record_ignores_missing_record():
    called = []

    finish_agent_run_record(
        None,
        result="done",
        tokens_in=1,
        tokens_out=2,
        error=None,
        finalize=lambda *args, **kwargs: called.append((args, kwargs)),
    )

    assert called == []


def test_finish_agent_run_record_suppresses_finalize_failure():
    warnings = []
    record = AgentRunRecord(Path("/tmp/run.md"), Path("/tmp/run.json"))

    def finalize(*args, **kwargs):
        raise RuntimeError("manifest locked")

    finish_agent_run_record(
        record,
        result="done",
        tokens_in=1,
        tokens_out=2,
        error="boom",
        finalize=finalize,
        warn=warnings.append,
    )

    assert warnings == ["更新子 Agent 运行记录失败: manifest locked"]

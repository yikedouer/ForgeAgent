"""Sub-agent run record helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agent_store import create_agent_run, finalize_agent_run


CreateAgentRunFn = Callable[..., tuple[Path, Path]]
FinalizeAgentRunFn = Callable[..., None]
WarnFn = Callable[[str], None]


@dataclass(frozen=True)
class AgentRunRecord:
    md_path: Path
    json_path: Path


def begin_agent_run_record(
    *,
    workspace: str,
    agent_id: str,
    description: str,
    subagent_type: str,
    model: str,
    prompt: str,
    create: CreateAgentRunFn = create_agent_run,
    warn: WarnFn | None = None,
) -> AgentRunRecord | None:
    try:
        md_path, json_path = create(
            workspace=workspace,
            agent_id=agent_id,
            name=description.replace(" ", "-").lower()[:40],
            description=description,
            subagent_type=subagent_type,
            model=model,
            prompt=prompt,
        )
    except Exception as exc:
        if warn:
            warn(f"创建子 Agent 运行记录失败: {exc}")
        return None
    return AgentRunRecord(md_path, json_path)


def finish_agent_run_record(
    record: AgentRunRecord | None,
    *,
    result: str,
    tokens_in: int,
    tokens_out: int,
    error: str | None,
    finalize: FinalizeAgentRunFn = finalize_agent_run,
    warn: WarnFn | None = None,
) -> None:
    if record is None:
        return
    try:
        finalize(
            record.md_path,
            record.json_path,
            result=result or "(no output)",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
        )
    except Exception as exc:
        if warn:
            warn(f"更新子 Agent 运行记录失败: {exc}")

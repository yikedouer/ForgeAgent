"""子 Agent 运行记录持久化 — .md 输出文件 + .json manifest。

对齐 claw-code 的 Agent 存储设计：每个子 Agent 运行时生成两个文件：
  * ``{agent_id}.md``   — 可读的 Markdown 报告（任务、提示词、输出）
  * ``{agent_id}.json`` — 结构化 manifest（状态、时间戳、模型、token 用量）

存储目录默认为 ``<workspace>/.forgecc/agent-runs/``，
也可通过 ``FORGECC_AGENT_STORE`` 环境变量覆盖。
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
import time
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger(__name__)

# ── 存储路径 ──────────────────────────────────────────────

_DEFAULT_SUBDIR = ".forgecc/agent-runs"
MAX_AGENT_FILE_STEM_BYTES = 120


def get_store_dir(workspace: str) -> Path:
    """获取（并确保存在）子 Agent 输出存储目录。"""
    override = os.environ.get("FORGECC_AGENT_STORE")
    if override:
        d = Path(override).expanduser()
    else:
        d = Path(workspace) / _DEFAULT_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Manifest 数据结构 ────────────────────────────────────

@dataclass
class AgentManifest:
    """子 Agent 运行的结构化元数据。"""
    agent_id: str
    name: str
    description: str
    subagent_type: str
    model: str
    status: str             # "running" / "completed" / "failed"
    output_file: str
    manifest_file: str
    created_at: str
    completed_at: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


# ── 文件操作 ─────────────────────────────────────────────

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _validate_agent_id(agent_id: str) -> None:
    """拒绝会逃出 agent-runs 目录的 ID。"""
    if (
        not isinstance(agent_id, str)
        or not agent_id
        or not agent_id.strip()
        or Path(agent_id).name != agent_id
        or "\\" in agent_id
    ):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


def _agent_file_stem(agent_id: str) -> str:
    """将 agent_id 转成安全、稳定、不易碰撞的文件名 stem。"""
    if len(agent_id.encode("utf-8")) <= MAX_AGENT_FILE_STEM_BYTES:
        return agent_id
    suffix = "_" + hashlib.sha256(agent_id.encode()).hexdigest()[:8]
    prefix_budget = MAX_AGENT_FILE_STEM_BYTES - len(suffix)
    prefix = agent_id.encode("utf-8")[:prefix_budget].decode(
        "utf-8", errors="ignore"
    )
    return prefix + suffix


def create_agent_run(
    workspace: str,
    agent_id: str,
    name: str,
    description: str,
    subagent_type: str,
    model: str,
    prompt: str,
) -> tuple[Path, Path]:
    """创建子 Agent 的初始输出文件和 manifest。

    返回 ``(md_path, json_path)``。调用方在子 Agent 完成后
    应调用 :func:`finalize_agent_run` 更新状态。
    """
    _validate_agent_id(agent_id)
    store = get_store_dir(workspace)
    file_stem = _agent_file_stem(agent_id)
    md_path = store / f"{file_stem}.md"
    json_path = store / f"{file_stem}.json"

    # ── Markdown 输出文件 ──
    md_content = (
        f"# Agent Task\n\n"
        f"- **id**: {agent_id}\n"
        f"- **name**: {name}\n"
        f"- **description**: {description}\n"
        f"- **type**: {subagent_type}\n"
        f"- **created_at**: {_iso_now()}\n\n"
        f"## Prompt\n\n{prompt}\n\n"
        f"## Output\n\n*(running...)*\n"
    )
    md_path.write_text(md_content, encoding="utf-8")

    # ── JSON manifest ──
    manifest = AgentManifest(
        agent_id=agent_id,
        name=name,
        description=description,
        subagent_type=subagent_type,
        model=model,
        status="running",
        output_file=str(md_path),
        manifest_file=str(json_path),
        created_at=_iso_now(),
    )
    json_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.debug("子 Agent 运行记录已创建: %s", md_path)
    return md_path, json_path


def finalize_agent_run(
    md_path: Path,
    json_path: Path,
    result: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str | None = None,
) -> None:
    """更新子 Agent 的输出文件和 manifest 为最终状态。"""
    status = "failed" if error else "completed"

    # ── 更新 Markdown ──
    try:
        original = md_path.read_text(encoding="utf-8")
        updated = original.replace(
            "## Output\n\n*(running...)*",
            f"## Output\n\n{result or '(no output)'}",
        )
        if error:
            updated += f"\n\n## Error\n\n{error}\n"
        md_path.write_text(updated, encoding="utf-8")
    except Exception as exc:
        log.warning("更新子 Agent .md 文件失败: %s", exc)

    # ── 更新 JSON manifest ──
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        raw["status"] = status
        raw["completed_at"] = _iso_now()
        raw["tokens_in"] = tokens_in
        raw["tokens_out"] = tokens_out
        if error:
            raw["error"] = error
        json_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("更新子 Agent .json manifest 失败: %s", exc)

    log.info("子 Agent 运行 %s: %s  tokens=%d/%d",
             status, md_path.stem, tokens_in, tokens_out)

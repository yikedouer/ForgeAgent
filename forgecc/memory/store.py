"""记忆存储层 — 基于文件的持久化记忆，配合 MEMORY.md 索引。

存储布局::

    ~/.forgecc/projects/{project_hash}/memory/
        MEMORY.md           ← 自动生成的索引
        user_preferences.md ← 单独的记忆文件
        feedback_use_chinese.md
        ...

每个记忆文件使用 YAML Frontmatter（name / description / type）+ 正文。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import parse_frontmatter, format_frontmatter

# ── 常量 ───────────────────────────────────────────────

VALID_TYPES = {"user", "feedback", "project", "reference"}
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000
_INDEX_BYTE_TRUNCATION_MARKER = "\n\n[... truncated, index too large ...]"


# ── 数据类 ──────────────────────────────────────────────

@dataclass
class MemoryEntry:
    name: str
    description: str
    type: str          # user / feedback / project / reference
    filename: str
    content: str
    mtime: float       # epoch seconds — used for sorting & freshness


# ── 路径工具 ────────────────────────────────────────────

def _project_hash(workspace: str) -> str:
    return hashlib.sha256(workspace.encode()).hexdigest()[:16]


def _find_canonical_git_root(workspace: str) -> str | None:
    """查找规范化 git 根目录（跨 worktree 共享）。"""
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=workspace, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        # git-common-dir 返回共享 .git 目录的路径
        return str(Path(common).resolve().parent)
    except Exception:
        return None


def get_memory_dir(workspace: str) -> Path:
    """返回 *workspace* 的记忆目录，不存在则创建。

    优先级:
      1. ``FORGECC_MEMORY_DIR`` 环境变量（绝对覆盖）
      2. 规范化 git 根目录 → worktree 共享同一份记忆
      3. 回退到 sha256(workspace)
    """
    # 优先级 1: 环境变量覆盖
    override = os.environ.get("FORGECC_MEMORY_DIR")
    if override:
        d = Path(override).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # 优先级 2: 使用规范化 git 根目录（worktree 共享）
    canonical = _find_canonical_git_root(workspace) or workspace
    d = Path.home() / ".forgecc" / "projects" / _project_hash(canonical) / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower())
    slug = slug.strip("_")
    if not slug:
        slug = "memory_" + hashlib.sha256(text.encode()).hexdigest()[:8]
    return slug[:40]


def _memory_filename(mem_dir: Path, type_: str, name: str) -> str:
    """为记忆生成稳定文件名，避免不同名称的 slug 碰撞互相覆盖。"""
    base = f"{type_}_{_slugify(name)}"
    filename = f"{base}.md"
    existing = mem_dir / filename
    if not existing.exists():
        return filename

    try:
        meta, _ = parse_frontmatter(existing.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    if meta.get("name") == name and meta.get("type") == type_:
        return filename

    suffix = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"{base}_{suffix}.md"


def _truncate_utf8_bytes(text: str, max_bytes: int, marker: str) -> str:
    marker_bytes = marker.encode("utf-8")
    budget = max(max_bytes - len(marker_bytes), 0)
    clipped = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return clipped + marker


# ── 增删改查 ────────────────────────────────────────────────────

def list_memories(workspace: str) -> list[MemoryEntry]:
    """列出所有记忆，按 mtime 降序排列。"""
    mem_dir = get_memory_dir(workspace)
    entries: list[MemoryEntry] = []

    for f in mem_dir.iterdir():
        if not f.suffix == ".md" or f.name == "MEMORY.md":
            continue
        try:
            raw = f.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(raw)
            if not meta.get("name") or not meta.get("type"):
                continue
            t = meta["type"] if meta["type"] in VALID_TYPES else "project"
            entries.append(MemoryEntry(
                name=meta["name"],
                description=meta.get("description", ""),
                type=t,
                filename=f.name,
                content=body,
                mtime=f.stat().st_mtime,
            ))
        except Exception:
            continue

    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries


def save_memory(
    workspace: str,
    name: str,
    description: str,
    type_: str,
    content: str,
) -> str:
    """保存记忆文件并更新索引。返回文件名。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Memory name must be non-empty")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Memory description must be non-empty")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Memory content must be non-empty")
    if not isinstance(type_, str):
        raise ValueError(f"Invalid memory type '{type_}'. Must be one of {VALID_TYPES}")
    name = name.strip()
    description = description.strip()
    type_ = type_.strip()
    if type_ not in VALID_TYPES:
        raise ValueError(f"Invalid memory type '{type_}'. Must be one of {VALID_TYPES}")

    mem_dir = get_memory_dir(workspace)
    filename = _memory_filename(mem_dir, type_, name)
    text = format_frontmatter(
        {"name": name, "description": description, "type": type_},
        content,
    )
    (mem_dir / filename).write_text(text, encoding="utf-8")
    update_index(workspace)
    return filename


def delete_memory(workspace: str, filename: str) -> bool:
    """删除记忆文件并更新索引。"""
    if not isinstance(filename, str) or not filename:
        return False
    filename = filename.strip()
    if (
        not filename
        or filename == "MEMORY.md"
        or Path(filename).name != filename
        or "\\" in filename
    ):
        return False
    filepath = get_memory_dir(workspace) / filename
    if not filepath.is_file():
        return False
    filepath.unlink()
    update_index(workspace)
    return True


def load_memory_index(workspace: str) -> str:
    """加载 MEMORY.md，应用双重截断（200 行 / 25 KB）。"""
    index_path = get_memory_dir(workspace) / "MEMORY.md"
    if not index_path.exists():
        return ""

    try:
        content = index_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    # 行截断
    lines = content.split("\n")
    if len(lines) > MAX_INDEX_LINES:
        content = "\n".join(lines[:MAX_INDEX_LINES]) + \
            "\n\n[... truncated, too many memory entries ...]"

    # 字节截断
    if len(content.encode("utf-8")) > MAX_INDEX_BYTES:
        content = _truncate_utf8_bytes(
            content, MAX_INDEX_BYTES, _INDEX_BYTE_TRUNCATION_MARKER
        )

    return content


# ── 索引维护 ───────────────────────────────────────

def update_index(workspace: str) -> None:
    """从当前记忆文件重建 MEMORY.md。"""
    memories = list_memories(workspace)
    lines = ["# Memory Index", ""]
    for m in memories:
        lines.append(f"- **[{m.name}]({m.filename})** ({m.type}) — {m.description}")

    index_path = get_memory_dir(workspace) / "MEMORY.md"
    try:
        index_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        return

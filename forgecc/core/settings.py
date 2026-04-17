"""Runtime settings resolved from .env files and environment variables.

Resolution order (later wins):
  1. Built-in defaults
  2. ~/.forgecc/.env        (user-level)
  3. <workspace>/.env       (project-level)
  4. Real environment vars  (always highest priority)

Design: frozen dataclass with a factory classmethod. All external
configuration flows through this single entry point so the rest of
the codebase never touches os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# ── .env file loader (zero dependencies) ──────────────────────

def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Supports KEY=VALUE, quotes, comments."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # strip surrounding quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key:
            result[key] = val
    return result


def _load_env_cascade() -> dict[str, str]:
    """Layer .env files then real env vars. Later sources win."""
    merged: dict[str, str] = {}
    # 1. user-level
    merged.update(_parse_dotenv(Path.home() / ".forgecc" / ".env"))
    # 2. project-level
    merged.update(_parse_dotenv(Path.cwd() / ".env"))
    # 3. real env vars always override
    for key in list(merged.keys()):
        if key in os.environ:
            merged[key] = os.environ[key]
    # also pick up env vars not in any .env file
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "FORGECC_MODEL",
                "FORGECC_CTX_BUDGET", "FORGECC_MAX_ROUNDS", "FORGECC_WORKSPACE",
                "FORGECC_PERMISSION_MODE"):
        if key in os.environ:
            merged[key] = os.environ[key]
    return merged


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    context_budget: int  # max tokens the model can accept
    max_rounds: int      # safety cap on agent iterations
    workspace: str       # root directory the agent operates in
    permission_mode: str # 'readonly' / 'write' / 'prompt' / 'danger'

    @classmethod
    def resolve(cls) -> Settings:
        """Build settings from .env files + environment, applying sensible defaults."""
        env = _load_env_cascade()
        return cls(
            api_key=env.get("OPENAI_API_KEY", ""),
            base_url=env.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=env.get("FORGECC_MODEL", "qwen3.6-plus"),
            context_budget=int(env.get("FORGECC_CTX_BUDGET", "128000")),
            max_rounds=int(env.get("FORGECC_MAX_ROUNDS", "60")),
            workspace=env.get("FORGECC_WORKSPACE", os.getcwd()),
            permission_mode=env.get("FORGECC_PERMISSION_MODE", "prompt"),
        )

    def replace(self, **overrides) -> Settings:
        """Return a copy with selected fields replaced (since frozen)."""
        from dataclasses import asdict
        merged = {**asdict(self), **overrides}
        return Settings(**merged)

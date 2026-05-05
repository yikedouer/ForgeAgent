"""运行时设置 — 从 .env 文件和环境变量解析。

解析顺序（后者覆盖前者）：
  1. 内置默认值
  2. ~/.forgeagent/.env        （用户级）
  3. <workspace>/.env       （项目级）
  4. 真实环境变量           （始终最高优先级）

Provider 配置保持为 OpenAI-compatible 协议：
  * ``OPENAI_API_KEY`` — API key
  * ``OPENAI_BASE_URL`` — OpenAI-compatible endpoint
  * ``MODEL`` — 模型名，纯透传给 API

如果要在本地使用私有兼容端点，只需要把 endpoint
写入本地 ``.env`` 的 ``OPENAI_BASE_URL``，不要把平台预设提交进仓库。

设计：冻结 dataclass + 工厂 classmethod。所有外部配置通过此
单一入口流入，其余代码不直接触碰 os.environ。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .mcp import MCPServerConfig, parse_mcp_servers


_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o"
_MODEL_ENV_KEYS = ("MODEL", "FORGEAGENT_MODEL")  # legacy fallback kept for compatibility


def _str_env(env: dict[str, str], name: str) -> str:
    value = env.get(name, "")
    return value if isinstance(value, str) else ""


def _first_str_env(env: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = _str_env(env, name).strip()
        if value:
            return value
    return ""


def _resolve_provider(
    env: dict[str, str],
) -> tuple[str, str, str, str, str]:
    """Return ``(api_key, base_url, model, client_type, api_version)``.

    Only OpenAI-compatible protocol settings are resolved here. ``client_type``
    and ``api_version`` are retained for backward-compatible Settings objects,
    but they are always returned as ``("openai", "")``.
    """
    return (
        _str_env(env, "OPENAI_API_KEY").strip(),
        _str_env(env, "OPENAI_BASE_URL").strip() or _DEFAULT_BASE_URL,
        _first_str_env(env, _MODEL_ENV_KEYS) or _DEFAULT_MODEL,
        "openai",
        "",
    )


# ── .env 文件加载器（零依赖）──────────────────────────

def _parse_dotenv(path: Path) -> dict[str, str]:
    """解析 .env 文件为字典。支持 KEY=VALUE、引号、注释。"""
    if not path.is_file():
        return {}
    parsed = dotenv_values(path)
    return {
        str(key): value
        for key, value in parsed.items()
        if key and isinstance(value, str)
    }


def _load_env_cascade() -> dict[str, str]:
    """分层加载 .env 文件再叠加真实环境变量。后者覆盖前者。

    加载后会将结果写回 ``os.environ``（与 python-dotenv 的
    ``load_dotenv()`` 行为一致），使得其他模块可以直接
    通过 ``os.environ`` 读取 ``.env`` 中的配置。
    """
    merged: dict[str, str] = {}
    # 1. 用户级
    merged.update(_parse_dotenv(Path.home() / ".forgeagent" / ".env"))
    # 2. 项目级
    workspace = (
        os.environ.get("FORGEAGENT_WORKSPACE")
        or merged.get("FORGEAGENT_WORKSPACE")
        or ""
    ).strip()
    project_dir = Path(workspace).expanduser() if workspace else Path.cwd()
    merged.update(_parse_dotenv(project_dir / ".env"))
    # 3. 真实环境变量始终覆盖
    for key in list(merged.keys()):
        if key in os.environ:
            merged[key] = os.environ[key]
    # 也拾取不在任何 .env 文件中的环境变量
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL",
                "FORGEAGENT_MODEL",  # legacy
                "FORGEAGENT_CTX_BUDGET", "FORGEAGENT_MAX_ROUNDS", "FORGEAGENT_WORKSPACE",
                "FORGEAGENT_PERMISSION_MODE", "FORGEAGENT_LOG_LEVEL", "FORGEAGENT_LOG_FILE",
                "FORGEAGENT_SESSION_DIR", "FORGEAGENT_PLANS_DIR", "FORGEAGENT_HOOKS",
                "FORGEAGENT_PROMPT_CACHE", "FORGEAGENT_MCP_SERVERS"):
        if key in os.environ:
            merged[key] = os.environ[key]

    # 将 .env 文件中读到的值注入 os.environ（不覆盖已有的真实环境变量）
    # 这样 Provider 等模块可以直接通过 os.environ 读取 empId 等配置
    for key, value_text in merged.items():
        if key not in os.environ:
            os.environ[key] = value_text

    return merged


def _positive_int_env(env: dict[str, str], name: str, default: int) -> int:
    raw_value = env.get(name, str(default))
    if isinstance(raw_value, bool):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _permission_mode_env(env: dict[str, str]) -> str:
    value = (_str_env(env, "FORGEAGENT_PERMISSION_MODE") or "prompt").strip().lower()
    return value if value in {"readonly", "write", "prompt", "danger", "plan"} else "prompt"


def _workspace_env(env: dict[str, str]) -> str:
    workspace = _str_env(env, "FORGEAGENT_WORKSPACE").strip() or os.getcwd()
    return str(Path(workspace).expanduser())


def _hook_paths_env(env: dict[str, str]) -> tuple[str, ...]:
    raw_value = _str_env(env, "FORGEAGENT_HOOKS")
    parts = re.split(rf"[{re.escape(os.pathsep)},]", raw_value)
    return tuple(part.strip() for part in parts if part.strip())


def _bool_env(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw_value = _str_env(env, name).strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str         # OpenAI-compatible endpoint
    model: str
    context_budget: int   # 模型可接受的最大 token 数
    max_rounds: int       # Agent 迭代安全上限
    workspace: str        # Agent 操作的根目录
    permission_mode: str  # 'readonly' / 'write' / 'prompt' / 'danger'
    client_type: str = "openai"  # reserved; always OpenAI-compatible
    api_version: str = ""        # reserved for Settings compatibility
    hook_paths: tuple[str, ...] = ()
    prompt_cache: bool = False
    mcp_servers: tuple[MCPServerConfig, ...] = ()

    @classmethod
    def resolve(cls) -> Settings:
        """从 .env 文件 + 环境变量构建设置。

        Provider 只解析 OpenAI-compatible 协议配置：
          * OPENAI_API_KEY
          * OPENAI_BASE_URL
          * MODEL
        """
        env = _load_env_cascade()
        api_key, base_url, model, client_type, api_version = _resolve_provider(env)
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            context_budget=_positive_int_env(env, "FORGEAGENT_CTX_BUDGET", 128000),
            max_rounds=_positive_int_env(env, "FORGEAGENT_MAX_ROUNDS", 60),
            workspace=_workspace_env(env),
            permission_mode=_permission_mode_env(env),
            client_type=client_type,
            api_version=api_version,
            hook_paths=_hook_paths_env(env),
            prompt_cache=_bool_env(env, "FORGEAGENT_PROMPT_CACHE"),
            mcp_servers=parse_mcp_servers(_str_env(env, "FORGEAGENT_MCP_SERVERS")),
        )

    def replace(self, **overrides) -> Settings:
        """返回替换指定字段的副本（因为 frozen）。"""
        merged = {key: getattr(self, key) for key in self.__dataclass_fields__}
        merged.update(overrides)
        return Settings(**merged)

    def for_model(self, model: str) -> Settings:
        """为指定模型创建新 Settings，复用当前 OpenAI-compatible 端点。"""
        resolved_model = model.strip() or self.model
        return self.replace(model=resolved_model)

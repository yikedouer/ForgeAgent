"""运行时设置 — 从 .env 文件和环境变量解析。

解析顺序（后者覆盖前者）：
  1. 内置默认值
  2. ~/.forgecc/.env        （用户级）
  3. <workspace>/.env       （项目级）
  4. 真实环境变量           （始终最高优先级）

Provider 预设系统：将「服务商」和「模型」分离：
  * ``FORGECC_PROVIDER`` — 服务商名称（qwen / deepseek / openai / azure / gemini）
    决定 api_key、base_url 和客户端类型
  * ``FORGECC_MODEL`` — 具体模型名，纯透传给 API

如果未显式设置 FORGECC_PROVIDER，会从模型名前缀自动推断。

对于公司内部代理（iai.alibaba-inc.com）：
  * Azure 类型使用 ``AzureOpenAI`` 客户端，需 ``AZURE_API_VERSION``
  * Gemini 类型使用标准 ``OpenAI`` 客户端
  * 两者都需要 ``FORGECC_EMP_ID`` 请求头

设计：冻结 dataclass + 工厂 classmethod。所有外部配置通过此
单一入口流入，其余代码不直接触碰 os.environ。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .mcp import MCPServerConfig, parse_mcp_servers
from .settings_provider import _infer_provider, _resolve_provider, _str_env


# ── .env 文件加载器（零依赖）──────────────────────────

def _parse_dotenv(path: Path) -> dict[str, str]:
    """解析 .env 文件为字典。支持 KEY=VALUE、引号、注释。"""
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
        key = re.sub(r"^export\s+", "", key)
        val = val.strip()
        # 去除两端引号
        if val[:1] in ('"', "'"):
            quote = val[0]
            closing = val.find(quote, 1)
            if closing >= 0:
                val = val[1:closing]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].rstrip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
        if key:
            result[key] = val
    return result


def _load_env_cascade() -> dict[str, str]:
    """分层加载 .env 文件再叠加真实环境变量。后者覆盖前者。

    加载后会将结果写回 ``os.environ``（与 python-dotenv 的
    ``load_dotenv()`` 行为一致），使得其他模块可以直接
    通过 ``os.environ`` 读取 ``.env`` 中的配置。
    """
    merged: dict[str, str] = {}
    # 1. 用户级
    merged.update(_parse_dotenv(Path.home() / ".forgecc" / ".env"))
    # 2. 项目级
    workspace = (
        os.environ.get("FORGECC_WORKSPACE")
        or merged.get("FORGECC_WORKSPACE")
        or ""
    ).strip()
    project_dir = Path(workspace).expanduser() if workspace else Path.cwd()
    merged.update(_parse_dotenv(project_dir / ".env"))
    # 3. 真实环境变量始终覆盖
    for key in list(merged.keys()):
        if key in os.environ:
            merged[key] = os.environ[key]
    # 也拾取不在任何 .env 文件中的环境变量
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL",
                "FORGECC_PROVIDER", "FORGECC_MODEL",
                "FORGECC_CTX_BUDGET", "FORGECC_MAX_ROUNDS", "FORGECC_WORKSPACE",
                "FORGECC_PERMISSION_MODE", "FORGECC_LOG_LEVEL", "FORGECC_LOG_FILE",
                "FORGECC_SESSION_DIR", "FORGECC_PLANS_DIR", "FORGECC_HOOKS",
                "FORGECC_PROMPT_CACHE", "FORGECC_MCP_SERVERS",
                "DEEPSEEK_API_KEY", "QWEN_API_KEY", "GEMINI_API_KEY",
                "AZURE_API_KEY", "AZURE_ENDPOINT", "AZURE_API_VERSION",
                "FORGECC_EMP_ID"):
        if key in os.environ:
            merged[key] = os.environ[key]

    # 将 .env 文件中读到的值注入 os.environ（不覆盖已有的真实环境变量）
    # 这样 Provider 等模块可以直接通过 os.environ 读取 empId 等配置
    for key, val in merged.items():
        if key not in os.environ:
            os.environ[key] = val

    return merged


def _positive_int_env(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _permission_mode_env(env: dict[str, str]) -> str:
    value = (_str_env(env, "FORGECC_PERMISSION_MODE") or "prompt").strip().lower()
    return value if value in {"readonly", "write", "prompt", "danger", "plan"} else "prompt"


def _workspace_env(env: dict[str, str]) -> str:
    workspace = _str_env(env, "FORGECC_WORKSPACE").strip() or os.getcwd()
    return str(Path(workspace).expanduser())


def _hook_paths_env(env: dict[str, str]) -> tuple[str, ...]:
    raw = _str_env(env, "FORGECC_HOOKS")
    parts = re.split(rf"[{re.escape(os.pathsep)},]", raw)
    return tuple(part.strip() for part in parts if part.strip())


def _bool_env(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = _str_env(env, name).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str         # 对于 Azure 类型，存储 azure_endpoint
    model: str
    context_budget: int   # 模型可接受的最大 token 数
    max_rounds: int       # Agent 迭代安全上限
    workspace: str        # Agent 操作的根目录
    permission_mode: str  # 'readonly' / 'write' / 'prompt' / 'danger'
    client_type: str = "openai"  # 'openai' | 'azure'
    api_version: str = ""        # Azure API 版本号
    hook_paths: tuple[str, ...] = ()
    prompt_cache: bool = False
    mcp_servers: tuple[MCPServerConfig, ...] = ()

    @classmethod
    def resolve(cls) -> Settings:
        """从 .env 文件 + 环境变量构建设置。

        Provider 预设系统将「服务商」和「模型」分离：
          * FORGECC_PROVIDER 决定 api_key + base_url
          * FORGECC_MODEL 纯透传给 API
        未设置 FORGECC_PROVIDER 时从模型名前缀自动推断。
        """
        env = _load_env_cascade()
        api_key, base_url, model, client_type, api_version = _resolve_provider(env)
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            context_budget=_positive_int_env(env, "FORGECC_CTX_BUDGET", 128000),
            max_rounds=_positive_int_env(env, "FORGECC_MAX_ROUNDS", 60),
            workspace=_workspace_env(env),
            permission_mode=_permission_mode_env(env),
            client_type=client_type,
            api_version=api_version,
            hook_paths=_hook_paths_env(env),
            prompt_cache=_bool_env(env, "FORGECC_PROMPT_CACHE"),
            mcp_servers=parse_mcp_servers(_str_env(env, "FORGECC_MCP_SERVERS")),
        )

    def replace(self, **overrides) -> Settings:
        """返回替换指定字段的副本（因为 frozen）。"""
        merged = {key: getattr(self, key) for key in self.__dataclass_fields__}
        merged.update(overrides)
        return Settings(**merged)

    def for_model(self, model: str) -> Settings:
        """为指定模型创建新 Settings，自动解析对应的 Provider。

        用于子 Agent 选用与父 Agent 不同的模型。
        例如主 Agent 用 qwen3.6-plus，简单子 Agent 用 qwen3.5-flash。
        """
        env = _load_env_cascade()
        # 强制覆盖模型名
        env["FORGECC_MODEL"] = model
        # 如果原始 env 有显式 FORGECC_PROVIDER 则删除，让其从新模型名推断
        env.pop("FORGECC_PROVIDER", None)
        api_key, base_url, resolved_model, client_type, api_version = (
            _resolve_provider(env)
        )
        return self.replace(
            api_key=api_key,
            base_url=base_url,
            model=resolved_model,
            client_type=client_type,
            api_version=api_version,
        )

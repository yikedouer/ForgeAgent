# 测试规范

ForgeAgent 使用 pytest。当前全量测试为 `872 passed`。

## 常用命令

```bash
uv run python -m compileall -q forgeagent
uv run --extra test python -m pytest -q
uv run --extra test python -m pytest tests/core/test_engine.py -q
```

## 目录映射

| 源码 | 测试 |
|---|---|
| `forgeagent/toolkit.py` | `tests/test_toolkit.py` |
| `forgeagent/toolkit_schema.py` | `tests/test_toolkit_schema*.py` |
| `forgeagent/core/engine*.py` | `tests/core/test_engine*.py` |
| `forgeagent/core/providers.py` | `tests/core/test_providers.py`, `test_provider_*.py` |
| `forgeagent/core/settings.py` | `tests/core/test_settings*.py` |
| `forgeagent/core/permissions.py` | `tests/core/test_permissions.py` |
| `forgeagent/core/plan_mode.py` | `tests/core/test_plan_mode.py` |
| `forgeagent/core/subagent*.py` | `tests/core/test_subagent*.py` |
| `forgeagent/core/mcp/` | `tests/core/test_mcp.py` |
| `forgeagent/context/` | `tests/context/test_*.py` |
| `forgeagent/memory/` | `tests/memory/test_*.py` |
| `forgeagent/skills/` | `tests/skills/test_playbook.py` |
| `forgeagent/interface/` | `tests/interface/test_*.py` |
| `forgeagent/tools/` | `tests/tools/test_*.py` |

## Fixture

| Fixture | 说明 |
|---|---|
| `clean_catalog` | 每个测试隔离工具注册表 |
| `tmp_workspace` | 临时 workspace |
| `mock_settings` | 基础 Settings |
| `mock_provider` | 可控 Provider mock |
| `tmp_memory_dir` | 隔离记忆目录 |

## 测试要求

- 新工具至少覆盖注册、参数校验、权限/路径边界和成功路径。
- Provider 不发真实网络请求，用 Mock OpenAI client。
- Shell、文件写入、checkpoint、memory 测试必须使用临时目录。
- 计划模式和权限测试要覆盖拒绝路径。
- 上下文压缩测试要覆盖消息格式合法性，不能切断 assistant tool_call 与 tool result。

## 提交前检查

```bash
uv run python -m compileall -q forgeagent
uv run --extra test python -m pytest -q
git diff --check
```

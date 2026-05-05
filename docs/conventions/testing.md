# 测试规范

## 概览

- 测试框架：pytest 8+
- 当前用例：870 个
- 运行方式：`uv run pytest`
- 配置：`pyproject.toml` 中的 `[tool.pytest.ini_options]`

## 目录结构

```
tests/
├── conftest.py          # 全局 fixture
├── test_toolkit.py      # 工具注册表测试
├── test_toolkit_mcp.py  # MCP 工具桥接测试
├── test_toolkit_schema.py # JSON Schema 参数校验测试
├── test_toolkit_schema_value.py # JSON Schema value 校验测试
├── core/
│   ├── test_engine.py   # Agent 循环测试
│   ├── test_provider_types.py # Provider 响应类型测试
│   ├── test_provider_errors.py # Provider 错误分类测试
│   ├── test_providers.py # LLM Provider 测试
│   ├── test_settings_provider.py # Provider 预设解析测试
│   ├── test_settings.py  # 配置系统测试
│   ├── test_mcp.py       # MCP 配置/协议/生命周期测试
│   ├── test_runtime.py   # runtime 事件记录测试
│   ├── test_engine_loop_*.py # Engine loop/prompt/LLM/usage 测试
│   ├── test_engine_tools_*.py # 工具调用、计划工具、日志、结果回填测试
│   ├── test_engine_agents_*.py # 子 Agent runtime、记录、执行、team 测试
│   ├── test_engine_session_*.py # checkpoint、压缩、记忆、状态测试
│   ├── test_subagent_discovery.py # 自定义 Agent 发现测试
│   ├── test_subagent_tools.py # 子 Agent 工具集解析测试
│   └── ...
├── instruments/
│   ├── test_shell.py    # shell 工具测试
│   ├── test_reader.py   # read_file 工具测试
│   └── ...
├── context/
│   ├── test_compaction_tool_entries.py # 工具结果裁剪条目测试
│   ├── test_compaction_tiers.py # 无 LLM 压缩层测试
│   ├── test_compaction_tokens.py # 压缩 token 估算测试
│   ├── test_compaction.py  # 压缩管道测试
│   └── ...
├── interface/
│   ├── test_cli_startup.py # CLI 启动参数测试
│   ├── test_export_command.py # 离线导出命令测试
│   ├── test_repl.py        # REPL 命令测试
│   └── ...
├── memory/
│   ├── test_store.py    # 记忆存储测试
│   └── ...
└── skills/
    ├── test_playbook.py # 技能系统测试
    └── ...
```

**测试文件与源码并行**：`forgecc/core/engine.py` → `tests/core/test_engine.py`

## 全局 Fixture

| Fixture | Scope | 说明 |
|---------|-------|------|
| `clean_catalog` | function, autouse | 每个测试前保存并清空工具目录，测试后还原 |
| `tmp_workspace` | function | 返回临时工作目录（`tmp_path / "workspace"`） |
| `mock_settings` | function | 预填充的 Settings 实例（test-key、test-model） |
| `mock_provider` | function | MagicMock Provider，可控返回值 |
| `tmp_memory_dir` | function | 设置 `FORGECC_MEMORY_DIR` 到临时目录 |

## 命名规范

```python
# 文件名：test_<module>.py
# 函数名：test_<功能>_<场景>

def test_settings_resolve_uses_provider_preset():
    """Settings.resolve() 应正确加载 Provider 预设。"""
    ...

def test_shell_tool_rejects_outside_workspace():
    """shell 工具应拒绝工作区外的写操作。"""
    ...

def test_compaction_budget_truncation_preserves_system():
    """Budget 截断应保留系统提示词。"""
    ...
```

## 测试原则

1. **隔离性**：每个测试独立运行，不依赖其他测试的状态
   - `clean_catalog` autouse fixture 确保工具目录隔离
   - `tmp_memory_dir` 确保记忆存储隔离
   - `tmp_workspace` 确保文件操作隔离

2. **无网络依赖**：所有 LLM 调用使用 `mock_provider`
   - Provider.chat_stream() 用 MagicMock 返回预设响应
   - 不测试真实 API 连接

3. **快速执行**：870 用例 < 5 秒完成
   - 不使用 sleep 或等待
   - 文件 I/O 使用 tmp_path

4. **覆盖范围**：
   - 每个模块至少有对应的测试文件
   - 公开 API 100% 覆盖
   - 边界条件和错误路径必须覆盖

## 按模块运行

```bash
uv run pytest tests/core/           # 核心引擎
uv run pytest tests/instruments/     # 工具
uv run pytest tests/context/         # 上下文压缩
uv run pytest tests/memory/          # 记忆系统
uv run pytest tests/skills/          # 技能系统
uv run pytest tests/test_toolkit.py  # 工具注册表
uv run pytest tests/test_toolkit_schema.py  # 工具参数 schema
```

## 添加新测试

1. 在对应的 `tests/<module>/` 目录下创建 `test_<name>.py`
2. 使用全局 fixture（`tmp_workspace`、`mock_settings` 等）
3. 遵循命名规范：`test_<功能>_<场景>`
4. 运行 `uv run pytest tests/<module>/test_<name>.py -v` 验证
5. 确认全量测试通过：`uv run pytest`

## 常见模式

### Mock LLM 响应

```python
def test_engine_handles_text_response(mock_settings, mock_provider):
    from forgecc.core.engine import Engine
    from forgecc.core import Completion

    mock_provider.chat_stream.return_value = Completion(
        text="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )
    engine = Engine(mock_settings, mock_provider)
    result = engine.run("Hi")
    assert result == "Hello!"
```

### 临时工具注册

```python
def test_custom_tool():
    from forgecc.toolkit import instrument

    @instrument(name="test_tool", description="test", parameters={})
    def test_tool():
        return "ok"

    spec = toolkit.lookup("test_tool")
    assert spec.fn() == "ok"
    # clean_catalog fixture 会自动清理
```

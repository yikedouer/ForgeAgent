# 工具开发规范

## 新增工具步骤

### 1. 创建工具模块

在 `forgeagent/tools/` 下创建文件：

```python
from forgeagent.toolkit import tool


@tool(
    name="my_tool",
    description="简短说明工具做什么，什么时候用。",
    parameters={
        "text": {
            "type": "string",
            "description": "输入文本。",
        },
    },
    readonly=True,
    risk_level="read",
)
def my_tool(text: str) -> str:
    return text.upper()
```

### 2. 注册模块

在 `forgeagent/tools/__init__.py` 导入新模块：

```python
from forgeagent.tools import my_tool  # noqa: F401
```

模块导入时 `@tool()` 会把工具注册到 `toolkit._CATALOG`。

### 3. 编写测试

```python
from forgeagent import toolkit


def test_my_tool_registered():
    spec = toolkit.lookup("my_tool")
    assert spec.name == "my_tool"
    assert spec.readonly is True


def test_my_tool_runs():
    result = toolkit.run_one("call_1", "my_tool", {"text": "hello"})
    assert result.ok is True
    assert result.output == "HELLO"
```

## 参数

| 参数 | 说明 |
|---|---|
| `name` | LLM 调用的工具名，必须全局唯一 |
| `description` | 给模型看的使用说明，应写清使用时机 |
| `parameters` | JSON Schema object |
| `readonly` | 只读工具可并发 |
| `risk_level` | `read` / `write` / `danger` |

## 风险级别

| 级别 | 用途 |
|---|---|
| `read` | 只读查询、读取文件、搜索 |
| `write` | 创建、修改、删除 workspace 内文件 |
| `danger` | Shell、外部进程、可能产生副作用的操作 |

## 文件工具要求

- 所有路径都必须走 `tools.paths.resolve_workspace_path()`。
- 必须拒绝 workspace 外路径。
- 大文件读取要有限制。
- 写入工具要清晰报告目标路径和结果。
- 替换类工具必须避免模糊替换，最好要求唯一匹配。

## 返回值

工具 handler 返回字符串。错误应返回可读信息，帮助模型下一轮修正；不要泄露无关环境变量、密钥或本地私有路径。

## MCP 工具

MCP 远端工具不需要写 Python handler。配置 `FORGEAGENT_MCP_SERVERS` 后，`toolkit_mcp.py` 会把远端 tool 转成本地 `ToolSpec`，命名格式为：

```text
mcp__{server}__{tool}
```

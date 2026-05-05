# 工具开发规范

## 添加新工具的步骤

### 1. 创建工具文件

在 `forgecc/instruments/` 目录下创建新文件：

```python
# forgecc/instruments/my_tool.py

from forgecc.toolkit import instrument


@instrument(
    name="my_tool",
    description="工具的简短描述（会展示给 LLM）",
    parameters={
        "param1": {
            "type": "string",
            "description": "参数说明",
        },
        "param2": {
            "type": "boolean",
            "description": "可选参数",
            "default": False,
        },
    },
    readonly=False,      # True = 只读，可并发执行
    risk_level="write",  # "read" / "write" / "danger"
)
def my_tool(param1: str, param2: bool = False) -> str:
    """执行逻辑，返回字符串结果展示给 LLM。"""
    # 实现逻辑
    return "执行结果"
```

### 2. 注册工具

在 `forgecc/instruments/__init__.py` 中添加导入：

```python
from forgecc.instruments import my_tool  # noqa: F401
```

导入时 `@instrument()` 装饰器会自动将工具注册到全局目录 `_CATALOG`。

### 3. 编写测试

在 `tests/instruments/` 目录下添加测试：

```python
# tests/instruments/test_my_tool.py

from forgecc import toolkit

def test_my_tool_registered():
    spec = toolkit.lookup("my_tool")
    assert spec is not None
    assert spec.readonly is False

def test_my_tool_basic(tmp_workspace):
    spec = toolkit.lookup("my_tool")
    result = spec.fn(param1="test")
    assert "预期结果" in result
```

## 装饰器参数详解

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `name` | str | 是 | 工具名称，全局唯一 |
| `description` | str | 是 | 展示给 LLM 的描述，越清晰越好 |
| `parameters` | dict | 是 | JSON Schema 格式的参数定义 |
| `readonly` | bool | 否 | 只读工具可并发执行（默认 False） |
| `risk_level` | str | 否 | 权限级别：`read`/`write`/`danger`（默认 `read`） |

## 参数 Schema 格式

遵循 JSON Schema 子集：

```python
parameters={
    "filepath": {
        "type": "string",
        "description": "目标文件路径",
    },
    "content": {
        "type": "string",
        "description": "文件内容",
    },
    "encoding": {
        "type": "string",
        "description": "编码格式",
        "default": "utf-8",     # 有 default = 可选参数
        "enum": ["utf-8", "gbk", "latin-1"],
    },
}
```

## risk_level 选择指南

| 级别 | 适用场景 | 权限模式影响 |
|------|---------|-------------|
| `read` | 只读操作（搜索、读文件） | 所有模式均允许 |
| `write` | 修改操作（写文件、编辑） | PLAN/READONLY 模式拒绝 |
| `danger` | 高风险操作（删除、系统命令） | PROMPT 模式需确认，PLAN/READONLY/WRITE 拒绝 |

## readonly 并发策略

```
toolkit.run_batch(invocations):
  ├── 全部 readonly=True → ThreadPoolExecutor 并发
  ├── 全部 readonly=False → 顺序执行
  └── 混合 → 顺序执行（保守策略）
```

设计原则：只有确定无副作用的工具才标记 `readonly=True`。

## 最佳实践

1. **描述要精确**：LLM 靠描述决定是否调用，模糊描述会导致误用
2. **返回值要有用**：返回的字符串是 LLM 下一步推理的输入
3. **错误要明确**：抛出异常或返回清晰的错误信息，不要静默失败
4. **保持独立**：工具函数不应依赖 Engine 或 Provider，只通过参数和返回值交互
5. **最小权限**：能用 `read` 就不用 `write`，能用 `write` 就不用 `danger`

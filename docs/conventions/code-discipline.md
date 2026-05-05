# 代码纪律

## 核心原则

**简洁优先，最小依赖。定位根因，不做临时修复。**

## 依赖约束

- **仅两个三方依赖**：`openai`（LLM 交互）+ `rich`（TUI 渲染）
- 添加新依赖前必须论证：标准库能否实现？现有依赖能否覆盖？
- 测试依赖（`pytest`）仅限 dev 组

## 命名规范

| 对象 | 风格 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `plan_mode.py`, `agent_store.py` |
| 类 | PascalCase | `Engine`, `PermissionEnforcer`, `InstrumentSpec` |
| 函数/方法 | snake_case | `run_batch()`, `chat_stream()`, `for_model()` |
| 常量 | UPPER_SNAKE | `_PROVIDER_PRESETS`, `READ_ONLY_INSTRUMENTS` |
| 私有成员 | 前缀 `_` | `_CATALOG`, `_active_engine`, `_enforcer` |
| dataclass 字段 | snake_case | `context_budget`, `risk_level`, `api_version` |

## 类型注解

- 所有公开函数必须有类型注解（参数 + 返回值）
- 内部辅助函数建议有，不强制
- 优先使用 `dataclass` 而非裸 `dict`
- 使用 `from __future__ import annotations` 延迟求值（Python 3.11+）

## 数据类设计

- 不可变数据用 `@dataclass(frozen=True)`（如 `Playbook`, `InstrumentSpec`）
- 可变配置用 `@dataclass`（如 `Settings`）
- 避免继承，优先组合

## 异常处理

```python
# 项目自定义异常层次
ForgeError              # 基类
├── ConfigError         # 配置错误（缺失 API key 等）
├── ToolError           # 工具执行错误
└── ProviderError       # LLM 调用错误
```

- 业务异常用自定义异常类，不裸抛 `Exception`
- 工具函数中捕获异常后返回错误信息字符串（不让 Agent 循环崩溃）
- Provider 层做重试（指数退避），超出重试次数后抛 `ProviderError`

## 模块分层

单向依赖，禁止反向引用：

```
interface/ → core/ → toolkit.py ← instruments/
                ↓
          context/ / memory/ / skills/
```

- **绝对禁止**：instruments/ 导入 core/、core/ 导入 interface/
- **全局状态最小化**：仅 `toolkit._CATALOG`（工具目录）和 `engine._active_engine`（当前引擎引用）

## 文件组织

- 单文件行数是软约束，不用为压行数拆出 20-40 行的碎模块；超过约 350 行时需要有清晰职责边界
- 当前 Engine 以职责聚合为准：`engine_loop.py` 299 行、`engine_tools.py` 156 行、`engine_agents.py` 409 行、`engine_session.py` 365 行
- 相关功能放同一目录（如 memory/ 下的 store/recall/prefetch/frontmatter）
- `__init__.py` 只做导出，不放逻辑

## 字符串与格式化

- 用户可见的输出用 Rich markup（`[bold]`、`[red]` 等）
- 内部日志用 f-string
- 系统提示词用字符串拼接（`"\n".join(parts)`），不用模板引擎

## Git 规范

- 提交消息遵循 Conventional Commits：`feat:` / `fix:` / `refactor:` / `docs:` / `test:`
- 每个提交只做一件事
- 测试必须随代码一起提交

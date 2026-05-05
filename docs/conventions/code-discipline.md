# 代码纪律

## 原则

- 简洁优先：不要为“看起来架构完整”而拆分文件或制造抽象。
- 根因优先：修 bug 时先定位真实路径，再改代码。
- 本地优先：敏感 endpoint、key、header、公司平台配置只放本地 `.env`，不进仓库。
- 测试跟风险匹配：共享链路、工具执行、权限、上下文压缩必须有测试。

## 命名

| 对象 | 风格 | 示例 |
|---|---|---|
| 包/模块 | snake_case | `forgeagent`, `plan_mode.py` |
| 类 | PascalCase | `Engine`, `ToolSpec` |
| 函数/方法 | snake_case | `run_batch()` |
| 常量 | UPPER_SNAKE | `READ_ONLY_TOOLS` |
| 私有成员 | `_` 前缀 | `_CATALOG` |

命名要贴近 Agent/LLM 惯例：`tool`、`agent`、`memory`、`provider`、`context`、`prompt` 优先于含义模糊的内部术语。

## 分层约束

```text
interface -> core -> toolkit <- tools
                 \-> context / memory / skills
```

- `interface` 负责 CLI 和展示，不直接实现 Agent 决策。
- `core` 负责编排，不写具体工具逻辑。
- `tools` 只实现工具行为，路径必须经过 workspace 边界检查。
- `context`、`memory`、`skills` 尽量保持可单独测试。

允许的全局状态要少：

- `toolkit._CATALOG`：工具注册表。
- `core.engine._active_engine`：工具运行时定位当前 Engine。

## 文件大小

文件大小是软约束，不为压行数拆出碎模块。超过约 350 行时应检查是否存在清晰职责边界。

保留聚合文件的条件：

- 调用链高度相关。
- 拆分后只会增加跳转成本。
- 测试仍能覆盖关键分支。

## 依赖

新增依赖必须满足至少一项：

- 删除明显自研协议/解析代码。
- 降低安全或兼容风险。
- 是领域内成熟标准库。

运行时依赖保持少而稳定；测试依赖放 optional dependency。

## 错误处理

- Provider 层把 SDK 异常归一化为项目异常。
- 工具 handler 不应让 Agent 主循环崩溃，异常要转换为工具结果。
- 文件路径相关错误要明确指出 workspace 边界或缺失文件。
- 高风险操作由权限系统兜底，不只依赖提示词约束。

## 文档同步

改以下内容时必须同步文档：

- 环境变量。
- CLI 命令。
- 工具名称或参数。
- Skill / Agent 发现路径。
- 运行测试方式。

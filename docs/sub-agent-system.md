# 子 Agent 系统

子 Agent 用于把一个任务拆给隔离上下文执行。父 Agent 通过 `agent` 工具启动单个子 Agent，通过 `team` 工具并行启动多个子 Agent。

## 内置类型

| 类型 | 工具集 | 用途 |
|---|---|---|
| `explore` | 只读工具 | 代码搜索、结构分析 |
| `plan` | 只读工具 | 生成执行计划 |
| `verification` | 只读工具 + shell | 运行测试、构建验证 |
| `general` | 除 `agent` 外的全部工具 | 通用任务执行 |

`explore`、`plan`、`verification` 默认不写文件。`general` 可写文件，但仍受权限模式和 workspace 边界保护。

## 自定义 Agent

发现路径按优先级从低到高：

```text
~/.claude/agents/*.md
~/.forgeagent/agents/*.md
~/.agents/agents/*.md
$FORGEAGENT_AGENTS_DIR/*.md
<workspace>/.claude/agents/*.md
<workspace>/.forgeagent/agents/*.md
<workspace>/.agents/agents/*.md
```

`.claude` 和 `.forgeagent` 路径用于兼容已有资产；项目内推荐使用通用的 `.agents/agents`。

文件格式：

```markdown
---
name: reviewer
description: 代码审查，关注安全和可维护性
allowed-tools: read_file, grep_search, glob_search
---

你是代码审查 Agent。请阅读相关代码，输出结构化审查结果。
```

字段：

| 字段 | 必须 | 说明 |
|---|---|---|
| `name` | 是 | Agent 类型名 |
| `description` | 是 | 展示给父 Agent 的说明 |
| `allowed-tools` | 否 | 逗号分隔工具白名单；为空时使用 `general` 默认集 |

## `agent` 工具

```json
{
  "description": "查找鉴权入口",
  "prompt": "阅读路由和 middleware，说明鉴权流程",
  "type": "explore",
  "model": "small-model"
}
```

执行流程：

1. 按 `type` 找内置或自定义 Agent。
2. 如传入 `model`，创建复用当前 endpoint 的新 Settings。
3. 创建子 Engine。
4. 按类型过滤工具。
5. 运行子 Agent。
6. 将最终文本和 token 用量回传父 Engine。

## `team` 工具

```json
{
  "agents": [
    {"description": "搜索 API", "prompt": "列出所有 API 入口", "type": "explore"},
    {"description": "搜索 DB", "prompt": "列出所有数据库访问", "type": "explore"},
    {"description": "计划改造", "prompt": "基于发现结果制定计划", "type": "plan"}
  ]
}
```

`team` 使用线程池并行运行多个子 Agent，最多 8 个任务。适合代码审查、迁移评估、复杂问题拆分。

## 隔离边界

每个子 Agent 都有：

- 独立 transcript。
- 独立系统提示词。
- 按类型过滤后的工具集。
- 可选模型覆盖。
- 单独运行记录。

子 Agent 不会直接修改父 transcript；父 Agent 只接收最终文本结果。

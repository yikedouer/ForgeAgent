# 子 Agent 系统

## 概述

ForgeCC 支持主 Agent 通过 `agent` 工具派生子 Agent 执行隔离任务，通过 `team` 工具并行派生多个子 Agent。子 Agent 拥有独立的上下文和工具集，执行完成后将结果文本返回父对话。

## 内置类型

| 类型 | 权限 | 工具集 | 用途 |
|------|------|--------|------|
| **explore** | 只读 | read_file, glob_search, grep_search, shell | 代码搜索、结构分析 |
| **plan** | 只读 | 同 explore | 生成结构化计划 |
| **verification** | 只读 | 同 explore | 运行测试、构建验证 |
| **general** | 完整 | 除 agent 外的全部工具 | 通用任务执行（默认） |

> explore/plan/verification 共享 READ_ONLY_TOOLS 工具集（shell 设为只读模式），防止子 Agent 意外修改文件。

## 自定义 Agent

### 发现路径

按优先级从低到高，同名文件高优先级覆盖低优先级：

```
1. ~/.claude/agents/*.md       （兼容 Claude Code）
2. ~/.forgecc/agents/*.md      （用户级）
3. $FORGECC_AGENTS_DIR/*.md    （环境变量指定）
4. <cwd>/.claude/agents/*.md   （项目级兼容）
5. <cwd>/.forgecc/agents/*.md  （项目级，最高优先级）
```

### 文件格式

Markdown 文件，frontmatter 定义元数据，正文为系统提示词：

```markdown
---
name: my-reviewer
description: 代码审查专家，专注于安全和性能问题
allowed-tools: read_file, grep_search, glob_search
---

你是一个代码审查专家。请仔细阅读代码，关注以下方面：
1. 安全漏洞（SQL 注入、XSS、路径遍历等）
2. 性能瓶颈（N+1 查询、内存泄漏等）
3. 代码规范（命名、注释、错误处理等）

返回结构化的审查报告。
```

**frontmatter 字段**：
- `name`（必须）：Agent 名称，用于 `agent` 工具的 `type` 参数
- `description`（必须）：描述，展示在工具参数的 enum 中
- `allowed-tools`（可选）：逗号分隔的允许工具列表，为空则使用 general 默认集

## agent 工具

```json
{
  "name": "agent",
  "parameters": {
    "type": "explore | plan | verification | general | <custom-name>",
    "prompt": "任务描述",
    "model": "(可选) 指定子 Agent 使用的模型"
  }
}
```

执行流程：
1. 根据 `type` 查找内置类型或自定义 Agent 配置
2. 如指定 `model`，通过 `Settings.for_model()` 创建独立配置
3. 创建隔离 `Engine` 实例（独立上下文、过滤后的工具集）
4. 子 Engine 运行直到完成
5. 返回最终文本响应到父对话
6. token 计数累积到父引擎

## team 工具

```json
{
  "name": "team",
  "parameters": {
    "tasks": [
      {"type": "explore", "prompt": "搜索所有 API 端点"},
      {"type": "explore", "prompt": "搜索所有数据库查询"},
      {"type": "plan", "prompt": "制定重构计划", "model": "qwen3.5-flash"}
    ]
  }
}
```

team 使用 `ThreadPoolExecutor` 并行执行多个子 Agent，所有结果汇总后返回。适合需要多角度分析的场景。

## 工具过滤逻辑

```python
# 内置只读类型
READ_ONLY_TOOLS = {"read_file", "glob_search", "grep_search", "shell"}
VERIFICATION_TOOLS = READ_ONLY_TOOLS  # 含 shell 用于测试

# general 类型：全部工具减去 "agent"（防递归）
GENERAL_TOOLS = set(catalog().keys()) - {"agent"}

# 自定义 Agent：根据 allowed-tools 字段过滤
# allowed-tools 为空 → 使用 GENERAL_TOOLS
```

## 子 Agent 隔离模型

```
父 Engine（qwen3.6-plus）
  │
  ├── agent(type="explore") → 子 Engine（继承父模型）
  │     独立上下文、只读工具集
  │     运行完成 → 文本返回父对话
  │
  ├── agent(type="general", model="gpt-4o") → 子 Engine（azure/gpt-4o）
  │     独立上下文、完整工具集
  │     自动推断 Provider 切换
  │
  └── team(tasks=[...]) → ThreadPoolExecutor 并行
        子 Engine A（explore）
        子 Engine B（plan）
        子 Engine C（general）
        全部完成 → 汇总返回
```

每个子 Engine 都有：
- 独立的对话上下文（不污染父对话）
- 过滤后的工具集（根据类型限制）
- 独立的 token 计数（完成后累积到父）
- 可选的独立模型/Provider 配置

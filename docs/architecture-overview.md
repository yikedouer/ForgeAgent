# 架构总览

## 一句话定位

ForgeCC 是一个 Think→Act→Observe 循环驱动的 Coding Agent，核心引擎 `Engine` 协调 LLM、工具、上下文、记忆四大子系统。

## 模块分层

```
┌─────────────────────────────────────────────────┐
│                  interface/                       │
│   repl.py   directive.py   streamer.py   cli.py  │
│            （用户交互 & 系统提示词）                │
├─────────────────────────────────────────────────┤
│                    core/                         │
│   engine.py    providers.py    settings.py       │
│   subagent.py  permissions.py  plan_mode.py      │
│   agent_store.py  team.py  log.py                │
│            （Agent 循环 & 编排）                   │
├──────────────┬──────────────┬────────────────────┤
│  context/    │   memory/    │     skills/         │
│  compaction  │   store      │     playbook        │
│  collapse    │   recall     │     loader          │
│  checkpoint  │   prefetch   │     frontmatter     │
│（上下文压缩） │ （持久记忆）  │   （技能发现）       │
├──────────────┴──────────────┴────────────────────┤
│                  toolkit.py                       │
│        （装饰器驱动的全局工具注册表）                │
├─────────────────────────────────────────────────┤
│                tools/                       │
│   shell  reader  writer  editor  finder           │
│   agent  team    skill   memory                   │
│            （12 个内置工具实现）                    │
└─────────────────────────────────────────────────┘
```

## Agent 循环（Think→Act→Observe）

```
用户输入
  │
  ▼
┌──────────────────────────────────────┐
│           engine.run()               │
│  ┌─────────────────────────────┐     │
│  │  1. Think: Provider.chat_stream() │←── 系统提示词（directive.py）
│  │     发送上下文给 LLM                │←── 记忆注入（memory/recall.py）
│  │     流式接收响应                    │
│  ├─────────────────────────────┤     │
│  │  2. Act: 解析 tool_calls          │
│  │     权限检查（PermissionEnforcer）  │
│  │     toolkit.run_batch() 执行      │
│  │     ├── readonly 工具 → 并发       │
│  │     └── write 工具 → 顺序         │
│  ├─────────────────────────────┤     │
│  │  3. Observe: 工具结果入上下文      │
│  │     上下文压缩检查（六层管道）      │
│  │     未完成 → 回到 Think            │
│  └─────────────────────────────┘     │
│              ↓ 完成                   │
│     返回最终文本响应                   │
└──────────────────────────────────────┘
```

循环终止条件：
- 模型返回纯文本（无 tool_calls）→ 正常完成
- 达到 `max_rounds` 上限 → 强制终止
- 上下文 token 超出 `context_budget` → 触发压缩后继续

## 上下文六层压缩管道

当 token 计数接近 `context_budget` 时，按顺序逐层应用：

| 层 | 机制 | 说明 |
|----|------|------|
| 1 | Budget 截断 | 丢弃最旧的消息，保留系统提示词和最近消息 |
| 2 | Snip 过时消息 | 标记长时间未引用的工具结果为 `[snipped]` |
| 3 | Microcompact 聚合 | 合并连续的同类工具结果为摘要 |
| 4 | Context Collapse 投影 | 将完整消息替换为结构化投影视图 |
| 5 | Autocompact 触发 | 主动调用 LLM 生成对话摘要 |
| 6 | 紧急裁剪 | 最后手段，强制丢弃直到满足 budget |

## 权限系统

五层权限模式（从严到宽）：

| 模式 | read | write | danger | 适用场景 |
|------|------|-------|--------|---------|
| PLAN | ✅ | ❌ | ❌ | 计划模式（只读规划） |
| READONLY | ✅ | ❌ | ❌ | 代码审查 |
| WRITE | ✅ | ✅ | ❌ | 日常开发 |
| PROMPT | ✅ | ✅ | ⚠️ 确认 | **默认模式** |
| DANGER | ✅ | ✅ | ✅ | 完全信任 |

工作区边界保护：所有 write 级工具检查 filepath 是否在 `Settings.workspace` 内，防止 Agent 越界写文件。

## 数据流全景

```
启动阶段：
.env → Settings.resolve() → Provider(client) → Engine → REPL

每轮交互：
用户输入 → engine.run()
  → directive.build() 组装系统提示词
  → memory.prefetch 预取记忆
  → Provider.chat_stream() → LLM
  → 解析响应 → tool_calls?
     ├── 是 → permissions.check() → toolkit.run_batch()
     │         → 结果入上下文 → 压缩检查 → 继续循环
     └── 否 → 输出文本 → 结束

子 Agent 调用：
  agent/team 工具 → Engine.execute_sub_agent()
  → 创建隔离 Engine 实例（独立上下文）
  → 子 Engine 运行 → 返回文本到父对话
  → token 计数累积到父引擎
```

## 核心类关系

| 类 | 文件 | 职责 |
|----|------|------|
| `Engine` | core/engine.py | Agent 主循环、子 Agent 调度、上下文管理 |
| `Provider` | core/providers.py | OpenAI/Azure 客户端封装、流式调用、重试 |
| `Settings` | core/settings.py | 配置加载、Provider 预设、for_model() |
| `PermissionEnforcer` | core/permissions.py | 权限检查、工作区边界、交互确认 |
| `SubAgent` | core/subagent.py | 内置类型定义、自定义 Agent 发现 |
| `Directive` | interface/directive.py | 系统提示词 7 大节组装 |
| `Repl` | interface/repl.py | REPL 命令循环、会话管理 |
| `ToolSpec` | toolkit.py | 工具元数据 + 执行函数封装 |

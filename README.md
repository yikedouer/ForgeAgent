# ForgeCC

从零构建的 Python coding agent，学习 [claw-code](https://github.com/ultraworkers/claw-code)（Claude Code）的核心设计思想，用 Python 逐步复现其架构。这是一个学习项目，旨在深入理解 Agent 架构的每一层设计。

## 特性

- **Agent 循环** — think → act → observe，LLM 自主决定何时停止
- **8 个内置工具** — shell、read_file、write_file、edit_file、glob_search、grep_search、delegate、skill
- **四级权限系统** — READONLY / WRITE / PROMPT / DANGER，危险操作交互确认
- **工作区边界保护** — 文件写入操作限制在项目目录内
- **三层上下文压缩** — Distill → Condense → Prune，自动管理长对话（配对安全切分）
- **结构化错误处理** — ContextWindowError 自动压缩重试，分层错误分类
- **Skill / Playbook 系统** — 基于 Markdown + YAML frontmatter 的可复用提示模板
- **流式输出** — 逐 token 实时打印
- **子代理委托** — 隔离上下文的 fork-and-return 模式
- **零配置依赖** — 仅需 `openai` + `rich`（2 个依赖）

## 环境准备

### 前置要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 使用 uv（推荐）

```bash
# 1. 进入项目目录
cd ForgeCC

# 2. 创建虚拟环境 + 安装依赖（一步完成）
uv sync

# 3. 运行
uv run forgecc
```

### 使用 pip

```bash
# 1. 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows

# 2. 安装（开发模式）
pip install -e .

# 3. 运行
forgecc
```

## 配置

ForgeCC 通过 `.env` 文件和环境变量进行配置，加载优先级（后者覆盖前者）：

1. 内置默认值（qwen3.6-plus + DashScope）
2. `~/.forgecc/.env` — 用户级配置，跨项目共享
3. `项目目录/.env` — 项目级配置
4. 环境变量 — 最高优先级，临时覆盖

### 配置项

在 `.env` 文件中设置：

```env
# API 密钥（必填）
OPENAI_API_KEY=sk-your-key-here

# API 地址（默认 DashScope）
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型名称（默认 qwen3.6-plus）
FORGECC_MODEL=qwen3.6-plus

# 上下文窗口预算（默认 128000）
FORGECC_CTX_BUDGET=128000

# 最大循环轮次（默认 60）
FORGECC_MAX_ROUNDS=60

# 权限模式（默认 prompt）
# 可选值：readonly / write / prompt / danger
FORGECC_PERMISSION_MODE=prompt
```

也可通过 CLI 参数覆盖：

```bash
uv run forgecc --api-key sk-xxx --base-url https://... -m gpt-4o
```

## 使用方式

### 交互模式（默认）

```bash
uv run forgecc
```

进入 REPL 后直接输入任务描述，例如：

```
You > 帮我看一下当前目录结构
You > 写一个快速排序函数并测试
You > /review          ← 调用 review skill
```

### 单次执行

```bash
uv run forgecc -p "读取 pyproject.toml 并告诉我项目名"
```

### 恢复会话

```bash
uv run forgecc -r <session_id>
```

### REPL 内置命令

内置命令**不带斜杠**，直接输入；Skill 调用**带斜杠** `/skillname`。

| 命令 | 说明 |
|------|------|
| `help` | 显示所有可用命令 |
| `save` | 保存当前会话 |
| `sessions` | 列出已保存的会话 |
| `usage` | 显示 token 用量 |
| `cost` | 估算本次会话 token 费用 |
| `skills` | 列出可用 skill |
| `model` | 查看当前模型 |
| `model <name>` | 切换模型（如 `model gpt-4o`） |
| `compact` | 手动触发对话压缩 |
| `clear` | 清空当前对话 |
| `diff` | 显示 git diff 统计 |
| `/skillname [args]` | 调用指定 skill |
| `exit` / `quit` | 退出 |

### 权限模式

ForgeCC 的每个工具都标注了风险等级（`read` / `write` / `danger`），权限模式控制哪些操作被允许：

| 模式 | 读取 | 写入 | 危险操作（shell 等） |
|------|------|------|---------------------|
| `readonly` | 允许 | 拒绝 | 拒绝 |
| `write` | 允许 | 允许 | 拒绝 |
| `prompt`（默认） | 允许 | 允许 | 交互确认 |
| `danger` | 允许 | 允许 | 允许 |

设置方式：`.env` 中 `FORGECC_PERMISSION_MODE=prompt` 或 CLI 环境变量。

## 项目结构

```
ForgeCC/
├── .env                         # 项目配置（API key 等）
├── pyproject.toml               # 构建配置
├── .forgecc/skills/             # Skill 模板目录
│   ├── review/SKILL.md          #   代码审查 skill
│   └── commit/SKILL.md          #   自动提交 skill
│
└── forgecc/                     # 源码
    ├── toolkit.py               # 装饰器注册式工具系统（含权限 enforcer 集成）
    │
    ├── core/                    # 引擎内核
    │   ├── engine.py            #   Agent 循环（think → act → observe）
    │   ├── providers.py         #   LLM 适配 + 流式 + 重试 + 结构化错误
    │   ├── settings.py          #   配置加载（.env + 环境变量）
    │   ├── permissions.py       #   四级权限系统 + 工作区边界检查
    │   └── errors.py            #   结构化错误层次（ForgeError 家族）
    │
    ├── context/                 # 上下文管理
    │   ├── compaction.py        #   三层压缩（Distill/Condense/Prune + 配对安全切分）
    │   └── checkpoint.py        #   会话持久化（UTF-8 中文友好）
    │
    ├── skills/                  # Playbook 系统
    │   ├── frontmatter.py       #   YAML frontmatter 解析
    │   └── playbook.py          #   Skill 发现 + 解析 + 执行
    │
    ├── instruments/             # 工具实现（每个工具标注 risk_level）
    │   ├── shell.py             #   Shell 命令（两阶段安全 + danger 级别）
    │   ├── reader.py            #   文件读取（read 级别）
    │   ├── writer.py            #   文件写入（write 级别）
    │   ├── editor.py            #   搜索替换编辑（write 级别）
    │   ├── finder.py            #   glob + grep 搜索（read 级别）
    │   ├── delegate.py          #   子代理委托（write 级别）
    │   └── skill.py             #   Skill 工具桥接（write 级别）
    │
    └── interface/               # 用户交互层
        ├── repl.py              #   CLI REPL + 12 个内置命令
        └── directive.py         #   系统提示动态组装
```

## 自定义 Skill

在 `.forgecc/skills/<name>/SKILL.md` 中创建：

```markdown
---
name: my-skill
description: 做某件事
context: inline
user-invocable: true
---

# 任务指令

请执行以下操作：
1. ...
2. ...

用户参数：$ARGUMENTS
```

- `context: inline` — 提示注入当前对话
- `context: fork` — 在隔离子引擎中执行
- `user-invocable: false` — 仅供 LLM 自动调用

## 源码学习指南

### 入口与调用链

整个系统的执行流如下（每一步都标注了源文件）：

```
python -m forgecc
│
├─ __main__.py              → from .interface.repl import main; main()
│
├─ interface/repl.py        → 解析 CLI 参数，创建 Settings → Provider → Engine
│   │                         启动 ForgeREPL.cmdloop() 或 one-shot 模式
│   │
│   └─ 用户输入 "帮我写个排序"
│      │
│      └─ engine.run(user_input)
│         │
│         ├─ 1. context/compaction.py  → maybe_compact() 检查是否需要压缩
│         ├─ 2. interface/directive.py → build() 组装系统提示词
│         ├─ 3. core/providers.py      → generate() 流式调用 LLM
│         ├─ 4. toolkit.py             → run_batch() 执行模型返回的工具调用
│         │     └─ instruments/*.py    → 具体工具实现
│         └─ 5. 结果写回 transcript，回到步骤 1（直到模型不再调工具）
```

### 推荐阅读顺序

按照「自底向上」的顺序，先理解基础设施，再看核心循环，最后看扩展能力：

| 阶段 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| **1. 配置层** | `core/settings.py` | ~94 | frozen dataclass + .env 多级加载 |
| **2. 权限系统** | `core/permissions.py` | ~122 | 四级权限模式 + 工作区边界检查 |
| **3. 错误体系** | `core/errors.py` | ~75 | ForgeError 层次 + 可重试分类 |
| **4. LLM 适配** | `core/providers.py` | ~225 | 流式调用 + 重试 + 结构化错误 |
| **5. 工具注册** | `toolkit.py` | ~155 | @instrument(risk_level=...) + enforcer |
| **6. 一个工具** | `instruments/reader.py` | ~62 | 最简单的工具，理解 @instrument 用法 |
| **7. 核心循环** | `core/engine.py` | ~163 | Agent Loop + 权限集成 + 自动压缩恢复 |
| **8. 系统提示** | `interface/directive.py` | ~101 | 动态组装 system prompt |
| **9. 上下文压缩** | `context/compaction.py` | ~198 | 三层压缩 + tool_use/tool_result 配对保护 |
| **10. CLI 交互** | `interface/repl.py` | ~321 | REPL + 12 个命令 + 权限确认回调 |
| **11. Skill 系统** | `skills/playbook.py` | ~177 | frontmatter 解析 + 发现 + inline/fork |
| **12. 子代理** | `instruments/delegate.py` | ~52 | spawn_delegate() 隔离执行 |

### 核心概念速查

| 概念 | 对应代码 | 一句话解释 |
|------|----------|------------|
| **Transcript** | `engine.transcript` | 就是 `list[dict]`，OpenAI 格式的消息列表 |
| **Instrument** | `toolkit.InstrumentSpec` | 一个函数 + 名称 + JSON Schema + risk_level |
| **Permission** | `permissions.PermissionEnforcer` | (mode × risk_level) 决定是否放行 |
| **Directive** | `directive.build()` | 每轮动态生成的 system prompt |
| **Compaction** | `compaction.maybe_compact()` | 上下文超预算时的三级降级策略 |
| **Playbook** | `skills/playbook.Playbook` | 一个 SKILL.md 解析后的 frozen dataclass |
| **Provider** | `core/providers.Provider` | 对 OpenAI SDK 的有状态封装（含 token 计数） |
| **Checkpoint** | `context/checkpoint` | 会话序列化为 JSON 文件 |

### 关键设计决策

1. **装饰器注册而非类继承** — 工具是函数不是类，`@instrument()` 自动注册到全局目录
2. **延迟导入打破循环** — engine ↔ interface 的循环依赖通过函数内 import 解决
3. **frozen dataclass** — Settings 和 Playbook 都是不可变的，修改通过 `replace()` 创建副本
4. **副作用导入触发注册** — `instruments/__init__.py` 导入所有子模块，触发 @instrument 装饰器执行
5. **toolkit 居于根层** — 作为 instruments 和 core 之间的桥梁，避免跨包循环依赖
6. **权限与工具声明分离** — risk_level 在 @instrument 上声明，enforcement 在 toolkit.run_one() 统一拦截
7. **压缩配对安全** — compaction 切分时向回走避免拆断 tool_use + tool_result 对
8. **ContextWindowError 自恢复** — 上下文超限自动 prune 并重试，无需用户干预

## License

MIT

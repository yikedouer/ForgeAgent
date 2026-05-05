# ForgeCC

从零构建的 Python Coding Agent，学习 [claw-code](https://github.com/ultraworkers/claw-code)（Claude Code 的 Rust 实现）的核心设计思想，用 Python 逐步复现其架构。

这是一个**学习项目**，旨在深入理解 Agent 架构从配置加载到上下文压缩的每一层设计。全部源码约 9,000 行，仅依赖 `openai` + `rich` 两个第三方库，适合一行一行阅读。

---

## 目录

- [特性一览](#特性一览)
- [架构总览](#架构总览)
- [快速开始](#快速开始)
- [配置系统](#配置系统)
- [使用方式](#使用方式)
- [项目结构](#项目结构)
- [核心概念详解](#核心概念详解)
- [模块深度拆解](#模块深度拆解)
- [数据流全景](#数据流全景)
- [源码学习路线](#源码学习路线)
- [关键设计决策](#关键设计决策)
- [测试体系](#测试体系)
- [自定义 Skill](#自定义-skill)
- [常见问题](#常见问题)
- [License](#license)

---

## 特性一览

| 能力 | 说明 |
|------|------|
| **Agent 循环** | Think → Act → Observe，LLM 自主决定何时调用工具、何时停止 |
| **12 个内置工具** | shell、read_file、write_file、edit_file、glob_search、grep_search、memory_save、memory_list、memory_delete、skill、agent、team |
| **多 Provider 支持** | Qwen / Azure(GPT) / Gemini / DeepSeek / OpenAI，Provider 与 Model 分离，灵活切换 |
| **子 Agent 级模型选择** | 主 Agent 和子 Agent 可使用不同模型（如主用 qwen3.6-plus，子用 qwen3.5-flash） |
| **四级权限系统** | READONLY / WRITE / PROMPT / DANGER + 工作区边界保护 |
| **六层上下文压缩** | Budget → Snip → Snip Stale → Microcompact → Context Collapse → Autocompact + 紧急裁剪 |
| **可逆上下文折叠** | LLM 生成旧消息摘要但**不修改原始记录**，投影视图隔离 |
| **持久化记忆系统** | 跨会话的 Agent 记忆——保存、语义召回、异步预取 |
| **计划模式** | 只读沙箱中生成计划，四选项审批后再执行 |
| **子 Agent 系统** | explore / plan / verification / general 四种内置类型 + 自定义 Agent 发现 + team 并行执行 |
| **Skill / Playbook** | 基于 Markdown + YAML frontmatter 的可复用提示模板 |
| **流式输出** | 逐 token 实时打印，结合 Rich 彩色面板 |
| **会话持久化** | 保存 / 恢复完整对话记录 |
| **零配置启动** | 仅需 `openai` + `rich`（2 个依赖） |

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        interface/repl.py                            │
│                     CLI REPL + 12 个内置命令                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ engine.run(user_input)
┌───────────────────────────────▼─────────────────────────────────────┐
│                         core/engine.py                              │
│              Agent 循环编排（Think → Act → Observe）                  │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐   │
│  │ Settings │  │ Provider │  │ Enforcer │  │ Compaction Pipeline│  │
│  │ 配置管理  │  │ LLM 调用 │  │ 权限执行  │  │ 上下文压缩         │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────────┘   │
└────────────┬───────────────────────────────────────┬────────────────┘
             │ toolkit.run_batch()                   │ memory/recall
┌────────────▼────────────────┐      ┌───────────────▼────────────────┐
│       toolkit.py            │      │         memory/                │
│  装饰器驱动的工具注册表       │      │  store + recall + prefetch     │
│  @instrument(risk_level=..) │      │  跨会话持久化记忆               │
└────────────┬────────────────┘      └────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────────────────┐
│                     instruments/                                    │
│  shell │ reader │ writer │ editor │ finder │ memory │ skill │ agent│
│  每个工具标注 risk_level（read / write / danger）                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 前置要求

- **Python >= 3.11**
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 方式一：uv（推荐，三步启动）

```bash
cd ForgeCC
uv sync                    # 创建虚拟环境 + 安装依赖
uv run forgecc             # 启动交互式 REPL
```

### 方式二：pip

```bash
cd ForgeCC
python -m venv .venv
source .venv/bin/activate  # macOS / Linux（Windows: .venv\Scripts\activate）
pip install -e .
forgecc
```

### 运行测试

```bash
uv pip install -e ".[test]"
python -m pytest tests/ -v
```

当前测试套件包含 **870 个用例**，覆盖全部 7 个模块。

---

## 配置系统

ForgeCC 通过 `.env` 文件和环境变量进行配置，采用**四层级联加载**（后者覆盖前者）：

```
内置默认值  →  ~/.forgecc/.env  →  项目目录/.env  →  环境变量
 (最低)          (用户级)            (项目级)         (最高)
```

`.env` 加载后会自动注入 `os.environ`（不覆盖已有变量），与 python-dotenv 的 `load_dotenv()` 行为一致。

### Provider 与 Model 分离

ForgeCC 采用 **Provider（服务商） + Model（模型）分离架构**：

- `FORGECC_PROVIDER` — 决定客户端类型、API 地址、认证方式
- `FORGECC_MODEL` — 纯透传给 API 的模型名

内置 5 种 Provider 预设：

| Provider | 客户端 | API 地址 | 默认模型 | 说明 |
|----------|--------|---------|---------|------|
| `qwen` | OpenAI | `dashscope.aliyuncs.com` | `qwen3.6-plus` | 通义千问 DashScope |
| `azure` | AzureOpenAI | `iai.alibaba-inc.com/azure` | `gpt-4.1-0414` | 公司内部 Azure 代理 |
| `gemini` | OpenAI | `iai.alibaba-inc.com/google` | `google/gemini-3.1-pro-preview` | 公司内部 Gemini 代理 |
| `deepseek` | OpenAI | `api.deepseek.com` | `deepseek-chat` | DeepSeek 直连 |
| `openai` | OpenAI | `api.openai.com/v1` | `gpt-4o` | OpenAI 官方 |

模型名前缀自动推断 Provider（无需显式指定）：`qwen*` → qwen, `gpt/o1/o3/o4` → azure, `google/*/gemini*` → gemini, `deepseek*` → deepseek。

### 配置项速查

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FORGECC_PROVIDER` | 自动推断 | 服务商：qwen / azure / gemini / deepseek / openai |
| `FORGECC_MODEL` | `qwen3.6-plus` | 模型名称（会反推 Provider） |
| `QWEN_API_KEY` | *(Qwen 必填)* | 通义千问 API 密钥 |
| `AZURE_API_KEY` | | Azure 代理 API 密钥 |
| `GEMINI_API_KEY` | | Gemini 代理 API 密钥 |
| `DEEPSEEK_API_KEY` | | DeepSeek API 密钥 |
| `OPENAI_API_KEY` | | OpenAI / 通用回退密钥 |
| `FORGECC_EMP_ID` | | 公司内部代理 empId 请求头 |
| `FORGECC_CTX_BUDGET` | `128000` | 最大上下文窗口（token 数） |
| `FORGECC_MAX_ROUNDS` | `60` | 单次任务最大循环轮次 |
| `FORGECC_PERMISSION_MODE` | `prompt` | 权限模式：readonly / write / prompt / danger |
| `FORGECC_WORKSPACE` | 当前目录 | 工作区根目录 |
| `FORGECC_SESSION_DIR` | `~/.forgecc/sessions` | 会话检查点与大型工具结果存储目录 |
| `FORGECC_PLANS_DIR` | `~/.forgecc/plans` | 计划模式文件存储目录 |
| `FORGECC_HOOKS` | | 本地 Hook 文件列表（用 `:` 或 `,` 分隔） |
| `FORGECC_PROMPT_CACHE` | `false` | 为 system prompt 添加 cache_control 标记 |
| `FORGECC_MCP_SERVERS` | | MCP server JSON 配置（支持 `mcpServers` 包装对象） |

### `.env` 文件示例

```env
# ── 切换服务商：只需改这两行 ──
FORGECC_PROVIDER=qwen
FORGECC_MODEL=qwen3.6-plus

# 服务商对应的 API Key
QWEN_API_KEY=sk-your-qwen-key
AZURE_API_KEY=your-azure-key
GEMINI_API_KEY=your-gemini-key

# 公司内部代理需要 empId
FORGECC_EMP_ID=123456
```

同一服务商内切换模型，只需改 `FORGECC_MODEL`：

```env
# FORGECC_MODEL=qwen3.6-plus
FORGECC_MODEL=qwen3.5-plus    # 切换到更轻量的模型
```

也可通过 CLI 参数覆盖：

```bash
uv run forgecc --api-key sk-xxx --base-url https://api.openai.com/v1 -m gpt-4o
```

---

## 使用方式

### 交互模式（默认）

```bash
uv run forgecc
```

进入 REPL 后直接输入任务描述：

```
You > 帮我看一下当前目录结构
You > 写一个快速排序函数并测试
You > /review               ← 调用 review skill
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

内置命令可直接输入，也可加斜杠作为别名；Skill 调用使用 `/skillname`。

| 命令 | 说明 |
|------|------|
| `help` | 显示所有可用命令 |
| `save` | 保存当前会话 |
| `sessions` | 列出已保存的会话 |
| `usage` | 显示 token 用量 |
| `cost` | 估算本次会话费用 |
| `skills` | 列出可用 skill |
| `model` | 查看当前模型 |
| `model <name>` | 切换模型（如 `model gpt-4o`） |
| `compact` | 手动触发对话压缩 |
| `clear` | 清空当前对话 |
| `diff` | 显示 git diff 统计 |
| `plan` | 切换计划模式（只读沙箱） |
| `/skillname [args]` | 调用指定 skill |
| `exit` / `quit` | 退出 |

### 权限模式

每个工具都标注了风险等级（`read` / `write` / `danger`），权限模式控制哪些操作被允许：

| 模式 \ 风险 | read | write | danger |
|-------------|------|-------|--------|
| `readonly` | 允许 | 拒绝 | 拒绝 |
| `write` | 允许 | 允许 | 拒绝 |
| `prompt`（默认） | 允许 | 允许 | 交互确认 |
| `danger` | 允许 | 允许 | 允许 |
| `plan` | 允许 | 拒绝 | 拒绝 |

---

## 项目结构

```
ForgeCC/
├── .env                             # 项目配置（Provider / API key 等）
├── pyproject.toml                   # 构建 + 测试配置
├── .forgecc/skills/                 # 项目级 Skill 模板目录
│
├── forgecc/                         # 源码包（~9,000 行）
│   ├── __init__.py                  #   版本声明
│   ├── __main__.py                  #   python -m forgecc 入口
│   ├── toolkit.py            (293)  #   装饰器驱动的工具注册表 + 权限执行 + Hook 事件
│   ├── toolkit_mcp.py         (73)  #   MCP 远端工具桥接 spec 构建
│   ├── toolkit_schema.py      (41)  #   工具参数 schema 入口
│   ├── toolkit_schema_value.py (277) # 递归 JSON Schema value 校验
│   │
│   ├── core/                        # ── 引擎内核 ──
│   │   ├── engine.py         (297)  #   Agent 核心门面 + public API
│   │   ├── providers.py      (289)  #   LLM 适配层（OpenAI / AzureOpenAI + 流式）
│   │   ├── provider_errors.py (40)  #   Provider 错误分类 + 重试判定
│   │   ├── provider_types.py  (50)  #   Completion / Invocation 响应类型
│   │   ├── settings.py       (213)  #   Settings dataclass + 四层级联加载
│   │   ├── settings_provider.py (107) # Provider/Model 预设解析
│   │   ├── mcp/                     #   MCP server 配置解析 + JSON-RPC/stdio 客户端
│   │   │   ├── config.py      (86)  #     server 配置 dataclass + Claude 风格 JSON 解析
│   │   │   ├── protocol.py   (133)  #     JSON-RPC client、协议类型、响应校验
│   │   │   ├── lifecycle.py   (60)  #     server 启动、工具注册、transport 关闭
│   │   │   └── stdio.py       (86)  #     newline-delimited JSON stdio transport
│   │   ├── permissions.py    (151)  #   四级权限 + 工作区边界检查
│   │   ├── hooks.py           (78)  #   运行时 Hook 注册与分发
│   │   ├── errors.py          (74)  #   结构化错误层级
│   │   ├── runtime.py         (41)  #   transcript 追加 + runtime JSONL event 记录
│   │   ├── engine_agent_execution.py (115) # 子 Agent 构造/运行/记录编排
│   │   ├── engine_agent_record.py (74) # 子 Agent 运行记录创建/收尾
│   │   ├── engine_checkpoint_api.py (41) # Engine checkpoint/model public API
│   │   ├── engine_checkpoint.py  (54) # Engine checkpoint 保存/恢复判定
│   │   ├── engine_compaction.py  (50) # Engine 手动压缩报告
│   │   ├── engine_init.py   (60)  #   Engine runtime 组件装配
│   │   ├── engine_llm.py     (45)  #   Engine LLM 调用 + 上下文恢复
│   │   ├── engine_memory.py   (94)  #   Engine 记忆预取 + 注入结果计算
│   │   ├── engine_plan_api.py (74) #  Engine 计划模式 public API
│   │   ├── engine_plan_tools.py (28) # 计划模式工具结果回填
│   │   ├── engine_prompt.py   (53)  #   系统提示词、投影视图和工具 schema 选择
│   │   ├── engine_round.py    (67)  #   单轮压缩、prompt、消息、schema 准备
│   │   ├── engine_run.py     (130)  #   Agent 单轮循环编排
│   │   ├── engine_state.py    (27)  #   Engine 会话状态重置
│   │   ├── engine_subagent.py (50)  #   子 Agent settings/provider 准备
│   │   ├── engine_subagent_entry.py (131) # Engine 子 Agent public API
│   │   ├── engine_team.py     (74)  #   team 子 Agent 并行执行与结果归集
│   │   ├── engine_tool_calls.py (48) # 工具调用准备与计划工具拆分
│   │   ├── engine_tool_execution.py (51) # 普通工具执行、持久化、回填
│   │   ├── engine_tool_logging.py (23) # 工具调用/结果日志格式化
│   │   ├── engine_tool_results.py (37) # 工具结果持久化与回填消息
│   │   ├── engine_usage.py   (33)  #   LLM completion token/time 统计
│   │   ├── plan_mode.py      (293)  #   计划模式（工具定义 + 状态机 + 提示词）
│   │   ├── subagent.py       (246)  #   子 Agent 内置类型 + 配置入口
│   │   ├── subagent_discovery.py (84) # 自定义 Agent 发现 + frontmatter
│   │   ├── subagent_tools.py  (25)  #   子 Agent 工具集解析
│   │   ├── agent_store.py    (185)  #   子 Agent 运行记录持久化
│   │   └── log.py             (76)  #   统一日志模块
│   │
│   ├── context/                     # ── 上下文管理 ──
│   │   ├── compaction.py     (169)  #   六层渐进式压缩管道入口
│   │   ├── compaction_autocompact.py (109) # LLM 摘要压缩层
│   │   ├── compaction_messages.py (43) # 压缩消息边界 helper
│   │   ├── compaction_tiers.py (174) # 无 LLM 压缩层级
│   │   ├── compaction_tool_entries.py (84) # 工具结果裁剪条目解析
│   │   ├── compaction_tokens.py (23) #   压缩 token 估算
│   │   ├── collapse.py       (162)  #   可逆上下文折叠（投影视图）
│   │   ├── tool_storage.py   (195)  #   大工具结果持久化到磁盘
│   │   └── checkpoint.py     (291)  #   会话检查点（UTF-8 中文友好）
│   │
│   ├── instruments/                 # ── 工具实现 ──
│   │   ├── reader.py          (97)  #   read_file — 带行号文件读取
│   │   ├── writer.py          (78)  #   write_file — 创建 / 覆写文件
│   │   ├── editor.py          (96)  #   edit_file — 唯一性约束的搜索替换
│   │   ├── finder.py         (148)  #   glob_search + grep_search
│   │   ├── shell.py          (291)  #   shell — 两阶段安全护栏
│   │   ├── memory.py         (153)  #   memory_save / list / delete
│   │   ├── skill.py           (73)  #   skill 调用桥接（inline / fork）
│   │   ├── agent.py           (89)  #   子 Agent 生成（explore / plan / verification / general）
│   │   └── team.py           (151)  #   team — 并行执行多个子 Agent
│   │
│   ├── memory/                      # ── 持久化记忆 ──
│   │   ├── store.py          (243)  #   记忆 CRUD + MEMORY.md 索引
│   │   ├── recall.py         (249)  #   语义召回（LLM 辅助选择）
│   │   ├── prefetch.py       (124)  #   异步记忆预取（三门控）
│   │   └── frontmatter.py     (54)  #   记忆文件 frontmatter 解析
│   │
│   ├── skills/                      # ── Playbook 系统 ──
│   │   ├── playbook.py       (190)  #   Skill 发现 + 解析 + 模板替换
│   │   └── frontmatter.py     (46)  #   Skill YAML frontmatter 解析
│   │
│   └── interface/                   # ── 用户交互层 ──
│       ├── repl.py           (235)  #   CLI REPL 壳层、Engine 生命周期、输入分派
│       ├── repl_commands.py  (256)  #   REPL 内置命令 + Skill 调用 + 计划模式命令
│       ├── one_shot.py        (54)  #   CLI 单次 prompt 输出 + 资源关闭
│       ├── cli_startup.py     (74)  #   CLI 启动参数校验 + Settings 覆盖
│       ├── export_command.py  (81)  #   离线 checkpoint export 命令
│       ├── export.py          (30)  #   transcript Markdown + event JSONL 渲染
│       ├── stats.py           (63)  #   工作区代码行数统计
│       ├── plan_approval.py   (50)  #   计划审批交互选项
│       └── directive.py      (279)  #   系统提示词动态组装（7 大节对齐 claw-code）
│
└── tests/                           # 测试套件（870 个用例）
    ├── conftest.py                  #   共享 fixtures
    ├── test_toolkit.py              #   工具注册表（81 用例）
    ├── test_toolkit_schema.py       #   JSON Schema 参数校验（4 用例）
    ├── core/                        #   核心层测试（310 用例）
    ├── context/                     #   上下文管理测试（144 用例）
    ├── instruments/                 #   工具实现测试（163 用例）
    ├── interface/                   #   用户交互测试（53 用例）
    ├── memory/                      #   记忆系统测试（89 用例）
    └── skills/                      #   技能系统测试（21 用例）
```

---

## 核心概念详解

### 1. Transcript（对话记录）

```python
engine.transcript = [
    {"role": "user",      "content": "帮我写个排序"},
    {"role": "assistant", "content": "好的，让我先查看...", "tool_calls": [...]},
    {"role": "tool",      "tool_call_id": "c1", "content": "文件内容..."},
    {"role": "assistant", "content": "排序函数已写好！"},
]
```

就是 `list[dict]`，完全兼容 OpenAI Chat Completion API 格式。Engine 的所有操作都围绕这个列表进行。

### 2. Instrument（工具）

```python
@instrument(
    name="read_file",
    description="Read a file with line numbers",
    parameters={...},       # JSON Schema
    readonly=True,
    risk_level="read",      # read / write / danger
)
def read_file(path: str) -> str:
    ...
```

工具是**普通函数**（不是类），通过 `@instrument()` 装饰器自动注册到全局目录 `_CATALOG`。装饰器在模块导入时执行，这就是为什么 `instruments/__init__.py` 会触发所有子模块的导入。

### 3. Permission Enforcer（权限执行器）

```
PermissionMode(prompt) × risk_level(danger) → 调用 prompter 交互确认
PermissionMode(write)  × risk_level(danger) → 直接拒绝
PermissionMode(danger) × risk_level(danger) → 直接放行
```

权限检查在 `toolkit.run_one()` 中统一执行，实现了「声明在工具上，执行在入口处」的关注点分离。

### 4. Compaction Pipeline（压缩管道）

上下文窗口有限，但长任务可能跨越几十轮并产生大量工具输出。压缩管道在**每次 LLM 调用前**自动触发，应用最轻量且足够的层级后停止：

| 层级 | 名称 | 触发阈值 | 策略 | 破坏性 |
|------|------|---------|------|--------|
| 1a | Budget | 50% | 基于利用率截断大工具结果（头尾保留） | 否 |
| 1b | Snip | 50% | 持久化超大结果到磁盘 + 摘要旧结果 | 否 |
| 2 | Snip Stale | 60% | read_file 去重 + 清除旧工具结果 | 否 |
| 2b | Microcompact | 空闲 >5min | 清除除最近 3 个外的所有旧结果 | 否 |
| 3 | Collapse | 75% | LLM 生成旧消息摘要（**可逆**，不修改原始记录） | 否 |
| 4 | Autocompact | 90% | LLM 生成结构化摘要（**破坏性**替换） | 是 |
| — | Prune | 95% | 硬回退——丢弃除系统 + 近期尾部外的所有内容 | 是 |

关键安全性：切分时**向回走**避免拆断 `tool_use` + `tool_result` 对。

### 5. Memory（持久化记忆）

```
~/.forgecc/projects/{hash}/memory/
    MEMORY.md               ← 自动生成的索引
    user_preferences.md     ← 单独的记忆文件（YAML frontmatter + 正文）
    feedback_use_chinese.md
```

记忆系统允许 Agent **跨会话**记住用户偏好、项目决策和反馈。召回流程：

1. **预取**：用户消息送入后，立即提交异步线程（与首次 LLM 调用并行）
2. **门控**：查询必须有实质内容 + 会话预算未超限 + 记忆文件存在
3. **选择**：将精简清单（文件名 + 描述）发送给模型，由其挑选最相关的（最多 5 个）
4. **注入**：注入到最后一条用户消息中

### 6. Plan Mode（计划模式）

Engine 可切换到**只读沙箱模式**：

1. 进入计划模式 → 权限降级为 `PLAN`（仅允许读取 + 编辑计划文件）
2. 模型在计划文件中写入实施方案
3. 退出计划模式 → 四选项审批：继续修改 / 保留上下文执行 / 清空上下文执行 / 手动执行
4. 审批通过 → 恢复原权限，开始执行

### 7. Sub-Agent（子 Agent）

```python
engine.execute_sub_agent(
    agent_type="explore",       # explore / plan / verification / general
    description="搜索认证代码",
    prompt="找到所有认证相关的...",
    model="qwen3.5-flash",      # 可选：为子 Agent 指定不同模型
)
```

子 Agent 获得**隔离的上下文**（看不到父对话），执行完成后将结果文本返回给父 Agent。Token 用量会汇聚回父引擎的累计计数器。

四种内置类型：

| 类型 | 工具集 | 用途 |
|------|--------|------|
| `explore` | 只读（read_file, glob_search, grep_search, shell） | 快速代码搜索和探索 |
| `plan` | 只读 | 分析架构并设计实施计划 |
| `verification` | 只读 | 运行测试 / lint / 构建验证代码变更 |
| `general` | 除 agent/team 外全部 | 独立完成复杂任务 |

并行执行（team 工具）：

```python
engine.execute_sub_agents_parallel([
    {"type": "explore", "description": "搜索认证", "prompt": "..."},
    {"type": "explore", "description": "搜索数据库", "prompt": "..."},
])
```

自定义 Agent：在 `.forgecc/agents/<name>.md` 中创建（YAML frontmatter + 系统提示词正文）。

---

## 模块深度拆解

### `core/settings.py` — 配置加载（213 行）

- `_parse_dotenv(path)` — 解析 `.env` 文件，支持引号值、注释行、空行
- `_load_env_cascade()` — 级联加载：用户级 → 项目级 → 真实环境变量，加载后注入 `os.environ`
- `_PROVIDER_PRESETS` — 5 种内置服务商预设（qwen / azure / gemini / deepseek / openai）
- `_MODEL_PREFIX_MAP` — 模型名前缀 → Provider 自动推断映射
- `_resolve_provider(env)` — 5 元组返回：(api_key, base_url, model, client_type, api_version)
- `Settings` — frozen dataclass，新增 `client_type`、`api_version`、`mcp_servers` 字段
- `Settings.for_model(model)` — 子 Agent 模型切换：从模型名推断 Provider 并创建新 Settings

### `core/mcp/` — MCP 配置、协议、生命周期与传输（389 行）

- `MCPServerConfig` — 标准化 MCP server 名称、启动命令、参数和环境变量
- `parse_mcp_servers(raw)` — 解析 Claude 风格 JSON，支持顶层 server 映射或 `mcpServers` 包装对象
- `MCPClient` — 同步 JSON-RPC 协议客户端，支持 initialize、tools/list、tools/call
- `MCPTransport` — transport 抽象，便于测试或接入其他传输
- `MCPServerManager` — 管理 MCP server 启动、工具注册、失败清理和 transport 关闭
- `StdioMCPTransport` — 官方 newline-delimited JSON stdio transport，负责子进程启动、读写和关闭

### `core/permissions.py` — 权限系统（151 行）

- `PermissionMode` — 枚举：READONLY / WRITE / PROMPT / DANGER / PLAN
- `PermissionEnforcer.check(risk_level, path, args)` — 核心判定逻辑
- `_check_workspace_boundary(path)` — 路径必须在 workspace 内，`..` 穿越被拒绝

### `core/providers.py` — LLM 适配（289 行）

- `Provider.__init__(settings)` — 根据 `client_type` 创建 OpenAI 或 AzureOpenAI 客户端
- 公司内部代理（`iai.alibaba-inc.com`）自动注入 `empId` 请求头
- `Provider.generate(messages, tool_schemas, on_token)` — 流式调用，返回 `Completion`
- `Provider.side_query(messages)` — 非流式查询（用于记忆召回 / 上下文折叠）
- `provider_types.Completion` — 包含 text、invocations、usage_in/out、raw_assistant_msg
- 错误映射：401→AuthenticationError, 429→RateLimitedError, 上下文超限→ContextWindowError
- 指数退避重试：可重试错误（429/502/503）最多重试 4 次

### `core/engine.py` — Engine 门面（297 行）

这是核心编排入口，保留 `Engine` 公共 API、状态初始化和兼容注入点；主循环已拆到 `core/engine_run.py`。`Engine.run()` 的伪代码：

```python
def run(self, user_input):
    return run_agent_loop(
        user_input=user_input,
        transcript=self.transcript,
        provider=self.provider,
        toolkit=self.toolkit,
        ...
    )
```

`engine_run.py` 的主循环：

```python
transcript.append(user_msg)
start_memory_prefetch(...)              # 异步预取记忆

for _ in range(max_rounds):
    maybe_compact(transcript, ...)      # 1. 压缩
    directive = build(...)              # 2. 组装系统提示词
    inject_recalled_memories(...)       # 3. 注入记忆
    completion = provider.generate      # 4. 调用 LLM
    transcript.append(assistant_msg)

    if no tool_calls:
        return completion.text          # 5a. 纯文本 → 结束

    results = toolkit.run_batch()       # 5b. 执行工具
    persist_if_large(results)           # 6. 大结果持久化
    transcript.extend(tool_results)     # 7. 回填结果，继续循环

return "(round budget exhausted)"
```

子 Agent 执行流程：

- `execute_sub_agent(type, description, prompt, model=None)` — 创建隔离子引擎并执行
- `execute_sub_agents_parallel(agents)` — ThreadPoolExecutor 并行执行多个子 Agent
- 模型切换：当指定 model 与父 Agent 不同时，通过 `settings.for_model()` 创建新 Provider
- Token 用量汇聚回父引擎的累计计数器

### `toolkit.py` — 工具注册表（293 行）

- `@instrument(name, description, parameters, readonly, risk_level)` — 注册装饰器
- `catalog()` — 返回所有工具的副本（修改不影响内部状态）
- `lookup(name)` — 查找单个工具
- `schemas()` — 返回 OpenAI tool schema 格式
- `run_one(call_id, name, args)` — 权限检查 → 执行 → 包装结果
- `run_batch(calls)` — 只读工具并发执行（ThreadPoolExecutor），写操作顺序执行

参数校验拆分在 `toolkit_schema.py`，MCP 远端工具适配拆分在 `toolkit_mcp.py`。

### `context/compaction.py` — 压缩管道入口（169 行）

编排六层压缩管道，轻量无 LLM 层级拆分在 `compaction_tiers.py`。关键函数：

- `_estimate_tokens(text)` — 粗略估算：`len(text) // 4`
- `_safe_split_point(messages, desired)` — 向回走避免拆断 tool_use/result 对
- `_budget_tool_results(messages, utilization)` — Tier 1a：头尾保留截断
- `_snip(messages, session_id)` — Tier 1b：持久化 + 摘要
- `_snip_stale_results(messages, utilization)` — Tier 2：去重 + 清除
- `_microcompact_idle(messages, last_api_call_time)` — Tier 2b：缓存冷却
- `_autocompact(messages, provider)` — Tier 4：LLM 生成摘要（含熔断器，实现在 `compaction_autocompact.py`）
- `_prune(messages)` — 紧急裁剪
- `maybe_compact(...)` — 公开入口，按利用率级联触发

### `memory/` — 持久化记忆系统

- `store.py` — CRUD 操作 + MEMORY.md 索引维护
- `recall.py` — 语义召回：扫描头部 → 格式化清单 → LLM 选择 → 加载内容
- `prefetch.py` — 异步预取：三门控（实质查询 + 预算 + 文件存在）→ 线程池提交
- `frontmatter.py` — 解析 `---\nkey: value\n---\nbody` 格式

---

## 数据流全景

### 完整执行流

```
python -m forgecc
│
├─ __main__.py                → from .interface.repl import main; main()
│
├─ interface/repl.py          → 解析 CLI 参数 → Settings.resolve() → Provider → Engine
│   │                           启动 ForgeREPL.cmdloop() 或 one-shot 模式
│   │
│   └─ 用户输入 "帮我写个排序"
│      │
│      └─ engine.run(user_input)
│         │
│         ├── memory/prefetch.py      → 异步预取相关记忆（与 LLM 调用并行）
│         │
│         ├── [循环开始]
│         │   ├── context/compaction.py   → maybe_compact() 检查上下文预算
│         │   ├── interface/directive.py  → build() 动态组装系统提示词
│         │   ├── memory/recall.py        → 注入预取到的记忆
│         │   ├── core/providers.py       → generate() 流式调用 LLM
│         │   │
│         │   ├── [无工具调用] → 返回文本给用户
│         │   │
│         │   └── [有工具调用]
│         │       ├── core/plan_mode.py   → 分离计划模式工具
│         │       ├── toolkit.py          → run_batch() 执行工具调用
│         │       │   ├── permissions.py  → 权限检查
│         │       │   └── instruments/*   → 具体工具实现
│         │       ├── tool_storage.py     → 大结果持久化到磁盘
│         │       └── 结果写回 transcript → 回到循环开始
│         │
│         └── [循环结束] → 返回文本或预算耗尽消息
```

### 权限执行流

```
toolkit.run_one(call_id, name, args)
│
├── lookup(name) → InstrumentSpec
│
├── enforcer.check(risk_level, path, args)
│   ├── mode × risk_level → 允许 / 拒绝 / 询问
│   └── _check_workspace_boundary(path) → 路径在 workspace 内？
│
├── [允许] → spec.fn(**args) → InstrumentResult(ok=True)
├── [拒绝] → InstrumentResult(ok=False, reason=...)
└── [异常] → InstrumentResult(ok=False, output=traceback)
```

---

## 源码学习路线

推荐按「自底向上」的顺序，先理解基础设施，再看核心循环，最后看扩展能力。

### 第一阶段：基础设施（奠定理解基础）

| 步骤 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| 1 | `core/settings.py` | 213 | Settings dataclass、.env 解析、四层级联加载 + os.environ 注入 |
| 2 | `core/settings_provider.py` | 107 | Provider/Model 分离、模型前缀推断、Azure/OpenAI endpoint 解析 |
| 3 | `core/errors.py` | 74 | 异常继承链、retryable 属性、isinstance 链 |
| 4 | `core/permissions.py` | 151 | 枚举 × 风险级别矩阵、工作区边界路径检查 |

> 学完这三个文件，你就理解了 Agent 的「安全底座」。

### 第二阶段：工具系统（理解 Agent 的「手」）

| 步骤 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| 4 | `toolkit.py` | 293 | @instrument 装饰器、全局目录、run_one/run_batch、工具 Hook |
| 5 | `toolkit_schema.py` | 41 | 工具参数 schema 入口——root object、unknown 参数、additionalProperties |
| 6 | `toolkit_schema_value.py` | 277 | JSON Schema value 校验——类型、组合 schema、数组/对象边界 |
| 6 | `instruments/reader.py` | 97 | **最简单的工具**——理解 @instrument 用法 |
| 7 | `instruments/shell.py` | 291 | 两阶段安全护栏（静态拒绝 + 超时保护） |
| 8 | `instruments/editor.py` | 96 | 唯一性约束设计——防止歧义修改 |

> 学完这五个文件，你就理解了工具从注册到执行的完整流程。

### 第三阶段：LLM 与核心循环（理解 Agent 的「脑」）

| 步骤 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| 9 | `core/providers.py` | 289 | 流式调用、工具调用解析、指数退避重试、Azure/Gemini 支持 |
| 10 | `core/provider_errors.py` | 40 | Provider 错误分类——上下文窗口、限流/连接重试判定 |
| 11 | `core/provider_types.py` | 50 | Provider 响应类型——Completion、Invocation、assistant 消息重建 |
| 11 | `interface/directive.py` | 279 | 系统提示词动态组装（7 大节对齐 claw-code + 记忆指导） |
| 12 | `core/engine.py` | 297 | **核心门面**——压缩 + 提示词 + LLM + 工具 + 记忆注入 + 子 Agent public API |

> 学完这三个文件，你就理解了 Agent 循环的完整编排逻辑。

### 第四阶段：上下文管理（理解 Agent 的「内存」）

| 步骤 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| 11 | `context/tool_storage.py` | 195 | 大结果持久化策略（30KB 即时 + 50K 旧版） |
| 12 | `context/collapse.py` | 162 | 可逆上下文折叠（投影视图不修改原始记录） |
| 13 | `context/compaction.py` | 169 | **六层压缩管道入口**——渐进式调度、折叠/裁剪入口 |
| 14 | `context/compaction_autocompact.py` | 109 | Autocompact——LLM 摘要、熔断器、压缩后文件路径恢复 |
| 15 | `context/compaction_tiers.py` | 174 | 无 LLM 压缩层——Budget/Snip/Snip Stale/Microcompact/Prune |
| 16 | `context/compaction_tool_entries.py` | 84 | 工具结果裁剪条目——tool call 参数解析、可裁剪结果收集 |
| 17 | `context/compaction_messages.py` | 43 | 压缩消息 helper——tool call 遍历、函数 payload、安全切分 |
| 18 | `context/compaction_tokens.py` | 23 | Token 估算——消息级和对话级粗略 token 计数 |

> 学完这三个文件，你就理解了 Agent 如何在有限窗口内处理超长对话。

### 第五阶段：扩展能力（理解 Agent 的「生态」）

| 步骤 | 文件 | 行数 | 学什么 |
|------|------|------|--------|
| 16 | `memory/store.py` | 243 | 记忆 CRUD + slugify + 索引维护 |
| 17 | `memory/recall.py` | 208 | 语义召回——LLM 辅助选择最相关的记忆 |
| 18 | `memory/prefetch.py` | 115 | 异步预取——三门控 + 线程池提交 |
| 19 | `skills/playbook.py` | 190 | Skill 发现 + frontmatter 解析 + 模板替换 |
| 20 | `core/subagent.py` | 246 | 子 Agent 类型系统——内置 Agent 配置 + 自定义 Agent 接入 |
| 21 | `core/subagent_discovery.py` | 84 | 自定义 Agent 发现——frontmatter、allowed-tools、多层目录覆盖 |
| 22 | `core/subagent_tools.py` | 25 | 子 Agent 工具集解析——配置/调用白名单 + 递归工具屏蔽 |
| 23 | `core/plan_mode.py` | 293 | 计划模式——只读沙箱 + 四选项审批 |
| 23 | `interface/cli_startup.py` | 74 | CLI 启动参数校验——resume/latest、输出格式、Settings 覆盖 |
| 24 | `interface/export_command.py` | 81 | 离线 checkpoint export 命令——Markdown/JSON/JSONL |
| 25 | `core/engine_agent_record.py` | 74 | 子 Agent 运行记录——创建/收尾失败降级 |
| 26 | `core/engine_agent_execution.py` | 115 | 子 Agent 执行编排——runtime、工具集、运行记录、异常转结果 |
| 27 | `core/engine_checkpoint.py` | 54 | Engine checkpoint 保存/恢复——快照构造 + 模型切换判定 |
| 28 | `core/engine_memory.py` | 94 | Engine 记忆——主 Agent 预取、prefetch 消费、浮现路径、预算统计 |
| 29 | `core/engine_plan_tools.py` | 28 | 计划工具结果回填——执行计划工具、fallback call id、tool 消息追加 |
| 30 | `core/engine_prompt.py` | 53 | Engine prompt 构建——系统提示词、投影视图、工具 schema 选择 |
| 31 | `core/engine_round.py` | 67 | 单轮输入准备——压缩、directive、wire messages、记忆注入、schema 选择 |
| 32 | `core/engine_llm.py` | 45 | Engine LLM 调用——Provider 调用、上下文超限裁剪重试 |
| 33 | `core/engine_state.py` | 27 | Engine 状态重置——清空会话、重置压缩/记忆/持久化跟踪 |
| 34 | `core/engine_subagent.py` | 50 | 子 Agent runtime——模型覆盖、Provider 重建、计划模式继承 |
| 35 | `core/engine_team.py` | 74 | Team 并行执行——线程池分派、完成顺序归位、线程错误转换、token 汇总 |
| 36 | `core/engine_tool_calls.py` | 48 | 工具调用准备——invocation 提取、计划工具拆分、回调失败降级 |
| 37 | `core/engine_tool_execution.py` | 51 | 工具执行编排——日志、批量执行、大结果持久化、transcript 回填 |
| 38 | `core/engine_tool_logging.py` | 23 | 工具日志格式化——参数预览、结果状态和输出长度 |
| 39 | `core/engine_tool_results.py` | 37 | 工具结果处理——大结果持久化、失败降级、tool 消息构造 |
| 40 | `core/engine_usage.py` | 33 | Token 统计——last input、API 调用时间、累计用量和日志字段 |
| 41 | `interface/one_shot.py` | 54 | CLI 单次执行——text/JSON 输出、token 用量、Engine 资源关闭 |
| 42 | `interface/repl.py` | 235 | CLI 交互壳层——输入分派、Engine 生命周期、权限确认回调 |
| 43 | `interface/repl_commands.py` | 256 | REPL 命令集——12 个命令 + Skill 调用 + 计划模式命令 |

> 学完全部 43 个文件（约 9,000 行），你就完整理解了一个生产级 Coding Agent 的架构。

---

## 关键设计决策

| # | 决策 | 原因 |
|---|------|------|
| 1 | **装饰器注册而非类继承** | 工具是函数不是类，`@instrument()` 自动注册到全局目录，避免复杂继承层级 |
| 2 | **frozen dataclass** | Settings / Playbook / InstrumentSpec 都是不可变的，修改通过 `replace()` 创建副本 |
| 3 | **toolkit 居于根层** | 作为 instruments 和 core 之间的桥梁，避免跨包循环依赖 |
| 4 | **权限与工具声明分离** | risk_level 在 @instrument 上声明，enforcement 在 toolkit.run_one() 统一拦截 |
| 5 | **延迟导入打破循环** | engine ↔ interface 的循环依赖通过函数内 `import` 解决 |
| 6 | **副作用导入触发注册** | `instruments/__init__.py` 导入所有子模块，触发装饰器执行完成工具注册 |
| 7 | **压缩配对安全** | 切分时向回走避免拆断 tool_use + tool_result 对，保证对话逻辑完整 |
| 8 | **ContextWindowError 自恢复** | 上下文超限自动 prune 并重试一次，无需用户干预 |
| 9 | **Autocompact 熔断器** | 连续 3 次 LLM 摘要失败 → 跳过，防止无限重试浪费 API |
| 10 | **记忆异步预取** | 与首次 LLM 调用并行执行，零延迟开销 |

---

## 测试体系

### 运行全部测试

```bash
python -m pytest tests/ -v
```

### 测试覆盖

| 模块 | 测试文件 | 用例数 | 覆盖内容 |
|------|---------|-------|---------|
| toolkit | `test_toolkit.py` | 81 | 装饰器注册、catalog/lookup、run_one/run_batch、工具 Hook、MCP 工具桥接 |
| toolkit MCP | `test_toolkit_mcp.py` | 3 | MCP 工具 spec 构建、远端名称路由、结果格式化 |
| toolkit schema | `test_toolkit_schema.py` | 4 | JSON Schema 参数校验、patternProperties、uniqueItems、必填参数 |
| toolkit schema value | `test_toolkit_schema_value.py` | 2 | JSON Schema value 校验、数值边界、嵌套对象 |
| settings | `core/test_settings.py` | 50 | .env 解析、级联加载、replace、for_model、Hook/MCP 配置 |
| settings provider | `core/test_settings_provider.py` | 3 | Provider 预设、模型前缀推断、Azure endpoint/API version 解析 |
| mcp | `core/test_mcp.py` | 20 | MCP server JSON 配置解析、JSON-RPC 握手、工具发现、工具调用、模块边界、生命周期管理、真实 stdio 冒烟、错误响应 |
| errors | `core/test_errors.py` | 12 | 继承链、retryable、status_code |
| log | `core/test_log.py` | 5 | 日志路径不可用时的降级、路径归一化 |
| hooks | `core/test_hooks.py` | 2 | Hook 注册、顺序分发、payload 隔离、本地 hook 文件加载 |
| permissions | `core/test_permissions.py` | 35 | 5×3 权限矩阵、prompter 交互、边界检查 |
| plan_mode | `core/test_plan_mode.py` | 14 | 常量、路径生成、提示词、状态切换、工具过滤 |
| providers | `core/test_providers.py` | 36 | 流式 Mock、错误分类、token 计数、Azure/Gemini、prompt cache 标记 |
| provider errors | `core/test_provider_errors.py` | 2 | 上下文窗口错误识别、限流/连接重试判定 |
| provider types | `core/test_provider_types.py` | 2 | Completion/Invocation assistant 消息重建、异常参数 fallback |
| runtime | `core/test_runtime.py` | 3 | transcript 追加、主 Agent JSONL 事件、子 Agent 事件跳过、失败降级 |
| engine agent execution | `core/test_engine_agent_execution.py` | 2 | 子 Agent 构造运行、工具集过滤、运行记录收尾、异常转结果 |
| engine agent record | `core/test_engine_agent_record.py` | 4 | 子 Agent 运行记录创建、创建/收尾失败降级、空记录跳过 |
| engine checkpoint | `core/test_engine_checkpoint.py` | 3 | checkpoint 快照构造、恢复时模型切换判定、保留当前模型 |
| engine compaction | `core/test_engine_compaction.py` | 1 | 手动压缩前后统计与 report 构建 |
| engine llm | `core/test_engine_llm.py` | 3 | LLM 调用成功路径、上下文超限裁剪重试、二次超限传播 |
| engine memory | `core/test_engine_memory.py` | 5 | 主 Agent 记忆预取、子 Agent 跳过预取、prefetch 注入和异常降级 |
| engine plan tools | `core/test_engine_plan_tools.py` | 2 | 计划工具执行、tool 消息回填、空 call id fallback |
| engine prompt | `core/test_engine_prompt.py` | 4 | 自定义/计划提示词、投影视图消息构建、工具 schema 选择 |
| engine round | `core/test_engine_round.py` | 2 | 单轮压缩、提示词、wire messages、记忆注入、schema 选择 |
| engine run | `core/test_engine_run.py` | 1 | Agent loop helper 纯文本收束、autosave、prefetch 状态写回 |
| engine state | `core/test_engine_state.py` | 1 | 清空会话时重置 transcript、压缩、记忆和持久化跟踪状态 |
| engine subagent | `core/test_engine_subagent.py` | 3 | 子 Agent 模型覆盖、Provider 复用/重建、计划模式继承 |
| engine team | `core/test_engine_team.py` | 5 | team 并行执行分派、原始顺序归集、线程异常转换、token 汇总 |
| engine tool calls | `core/test_engine_tool_calls.py` | 3 | 工具调用元组构建、计划工具拆分、工具回调异常降级 |
| engine tool execution | `core/test_engine_tool_execution.py` | 2 | 普通工具日志、批量执行、持久化、tool 消息回填和失败降级 |
| engine tool logging | `core/test_engine_tool_logging.py` | 3 | 工具调用参数预览、长值截断、工具结果状态日志格式 |
| engine tool results | `core/test_engine_tool_results.py` | 3 | 工具结果持久化成功/失败、tool transcript 消息构造 |
| engine usage | `core/test_engine_usage.py` | 1 | LLM completion 更新 last token/time、累计 token 和日志字段 |
| subagent | `core/test_subagent.py` | 23 | 内置/自定义 Agent 配置、描述生成、Agent store |
| subagent discovery | `core/test_subagent_discovery.py` | 3 | frontmatter、allowed-tools、多层目录覆盖 |
| subagent tools | `core/test_subagent_tools.py` | 4 | 子 Agent 工具集解析、调用白名单、递归工具屏蔽 |
| engine | `core/test_engine.py` | 48 | 初始化、基本循环、上下文恢复、模型切换、计划模式、子 Agent、记忆注入、会话重置、手动压缩、Hook/MCP 加载、运行时事件流 |
| checkpoint | `context/test_checkpoint.py` | 47 | save/load 往返、覆盖、异常、环境路径、JSONL 事件流 |
| collapse | `context/test_collapse.py` | 9 | 折叠/投影/不修改原始 |
| tool_storage | `context/test_tool_storage.py` | 22 | 持久化/预览/幂等、环境路径 |
| compaction | `context/test_compaction.py` | 49 | 压缩入口兼容导出、各层行为和主入口集成 |
| compaction tiers | `context/test_compaction_tiers.py` | 4 | 无 LLM 压缩层直接覆盖、工具映射、旧结果清理、紧急裁剪 |
| compaction autocompact | `context/test_compaction_autocompact.py` | 8 | LLM 摘要压缩、熔断器、失败计数、文件路径恢复 |
| compaction tool entries | `context/test_compaction_tool_entries.py` | 2 | snip-stale 工具参数解析、可裁剪工具结果收集 |
| compaction tokens | `context/test_compaction_tokens.py` | 3 | 字符到 token 估算、消息 token、对话 token 聚合 |
| instruments | `instruments/test_instruments.py` | 158 | reader/writer/editor/finder/shell/memory |
| skill instrument | `instruments/test_skill_instrument.py` | 5 | fork skill 到子 Agent 的桥接 |
| cli startup | `interface/test_cli_startup.py` | 7 | CLI 参数校验、resume/latest、Settings 覆盖、输出格式约束 |
| repl | `interface/test_repl.py` | 29 | slash 命令别名、skill 调用、模型/CLI 切换、token 显示、JSONL 导出、Engine 资源关闭 |
| one shot | `interface/test_one_shot.py` | 3 | CLI 单次 prompt 的 text/JSON 输出、token 用量和异常关闭 |
| export command | `interface/test_export_command.py` | 4 | 离线 checkpoint export、Markdown/JSON/JSONL、参数错误 |
| export | `interface/test_export.py` | 3 | transcript Markdown 渲染、checkpoint event JSONL 渲染 |
| plan approval | `interface/test_plan_approval.py` | 4 | 计划审批选项映射、反馈采集、无效输入重试 |
| stats | `interface/test_stats.py` | 3 | 工作区行数统计、目录过滤、排序 |
| frontmatter | `memory/test_frontmatter.py` | 11 | 解析/往返/空文本 |
| store | `memory/test_store.py` | 40 | CRUD/slugify/索引截断 |
| recall | `memory/test_recall.py` | 23 | 扫描/清单/选择/注入 |
| prefetch | `memory/test_prefetch.py` | 15 | 门控/全通过/句柄 |
| playbook | `skills/test_playbook.py` | 21 | frontmatter/发现/缓存/模板/描述 |
| **总计** | **60 个文件** | **870** | **全部 7 个模块的每个公开函数和关键边界条件** |

### 测试设计原则

- **全局状态隔离**：`clean_catalog` autouse fixture 每个测试前保存/清空/恢复工具目录
- **零 API 调用**：通过 Mock OpenAI 客户端完全隔离外部依赖
- **模块级缓存重置**：子 Agent 缓存、playbook 缓存、tool_storage 跟踪集合每个测试隔离

---

## 自定义 Skill

在 `.forgecc/skills/<name>/SKILL.md` 中创建：

```markdown
---
name: my-skill
description: 做某件事
context: inline
user-invocable: true
allowed-tools: read_file, grep_search
when-to-use: 当用户要求审查代码时
---

# 任务指令

请执行以下操作：
1. ...
2. ...

用户参数：$ARGUMENTS
技能目录：${SKILL_DIR}
```

### Frontmatter 字段

| 字段 | 说明 |
|------|------|
| `name` | 技能名称（用于 `/name` 调用） |
| `description` | 一句话描述 |
| `context` | `inline`（注入当前对话）或 `fork`（隔离子引擎） |
| `user-invocable` | `true`（用户可用 `/name` 调用）或 `false`（仅 LLM 自动调用） |
| `allowed-tools` | 限制子引擎可用工具（逗号分隔或 JSON 数组） |
| `when-to-use` | 提示 LLM 何时自动调用此技能 |

### 目录优先级

```
~/.forgecc/skills/    → 用户级（最低优先级）
.claude/skills/       → 兼容 Claude Code
.forgecc/skills/      → 项目级（最高优先级，同名覆盖用户级）
```

---

## 常见问题

### Q: 如何切换服务商（Provider）？

在 `.env` 中修改 `FORGECC_PROVIDER` 和 `FORGECC_MODEL`：

```env
# 切换到 Azure GPT
FORGECC_PROVIDER=azure
FORGECC_MODEL=gpt-4.1-0414

# 切换到 Gemini
FORGECC_PROVIDER=gemini
FORGECC_MODEL=google/gemini-3.1-pro-preview

# 切换到 OpenAI 官方
FORGECC_PROVIDER=openai
FORGECC_MODEL=gpt-4o
```

或者只改模型名，Provider 会自动推断：

```env
FORGECC_MODEL=gpt-4o          # 自动推断为 azure
FORGECC_MODEL=deepseek-chat    # 自动推断为 deepseek
```

### Q: 如何增大上下文窗口？

```env
FORGECC_CTX_BUDGET=200000
```

### Q: 如何跳过所有权限确认？

```env
FORGECC_PERMISSION_MODE=danger
```

> 仅在可信环境中使用。

### Q: 如何查看 Agent 的记忆？

记忆文件存储在 `~/.forgecc/projects/{hash}/memory/` 目录下，可直接查看 `.md` 文件，或在 REPL 中让 Agent 执行 `memory_list` 工具。

### Q: 为什么只有 2 个依赖？

设计原则是**最小依赖**。`openai` 提供 LLM 调用能力，`rich` 提供彩色终端输出。其余全部用 Python 标准库实现（包括 frontmatter 解析、shell 安全、.env 加载、会话持久化等）。

---

## License

MIT

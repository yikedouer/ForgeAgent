# 记忆与技能系统

## 记忆系统

### 设计目标

跨会话持久化 Agent 学到的知识，下次启动时自动注入系统提示词，让 Agent 记住项目上下文。

### 存储布局

```
~/.forgecc/projects/{project_hash}/memory/
├── MEMORY.md           # 索引文件（自动生成，双重截断：200行/25KB）
├── user_feedback_xxx.md
├── project_note_xxx.md
└── reference_xxx.md
```

路径解析优先级：
1. `FORGECC_MEMORY_DIR` 环境变量（绝对路径覆盖）
2. Git 根目录规范化后的哈希（worktree 共享同一份记忆）
3. 回退：`~/.forgecc/projects/{cwd_hash}/memory/`

### 记忆类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `user` | 用户偏好和反馈 | "我喜欢函数式风格" |
| `feedback` | Agent 学到的教训 | "这个项目用 Tab 缩进" |
| `project` | 项目级知识 | "数据库用 PostgreSQL 16" |
| `reference` | 参考资料 | "API 文档链接" |

### 记忆文件格式

```markdown
---
name: 项目使用 Tab 缩进
description: 代码风格偏好
type: feedback
---

用户明确要求所有代码使用 Tab 缩进而非空格。
ESLint 和 Prettier 配置已设置为 useTabs: true。
```

### 工具 API

| 工具 | 操作 | 说明 |
|------|------|------|
| `memory_save` | 保存 | 创建或更新记忆条目 |
| `memory_list` | 列出 | 显示所有记忆的名称和描述 |
| `memory_delete` | 删除 | 按文件名删除记忆 |

### 自动注入

1. **预取**：`start_memory_prefetch()` 在 Agent 循环开始前启动后台线程加载记忆索引
2. **召回**：`format_memories_for_injection()` 将记忆格式化为系统提示词片段
3. **注入**：`directive.build()` 将记忆片段附加到系统提示词末尾

### REPL 快捷方式

```
/memory           # 列出所有记忆
/remember <text>  # 快速保存一条反馈记忆
```

---

## 技能系统

### 设计目标

可扩展的提示词模板系统，通过 Markdown 文件定义可复用的任务模板。技能可以是用户手动调用（如 `/commit`）或 Agent 自动使用（通过 `skill` 工具）。

### 发现路径

按优先级从低到高，同名技能高优先级覆盖：

```
1. ~/.forgecc/skills/<name>/SKILL.md   （用户级）
2. <cwd>/.claude/skills/<name>/SKILL.md（兼容 Claude Code）
3. <cwd>/.forgecc/skills/<name>/SKILL.md（项目级，最高）
```

### 技能文件格式

```markdown
---
name: commit
description: 生成规范的 Git commit message
when-to-use: 用户要求提交代码或执行 /commit 时
user-invocable: true
allowed-tools: shell, read_file, grep_search
---

分析当前 git diff，生成符合 Conventional Commits 规范的提交消息。

$ARGUMENTS

步骤：
1. 运行 `git diff --cached` 查看暂存区变更
2. 分析变更内容，确定 type（feat/fix/refactor/docs 等）
3. 生成简洁的提交消息
4. 使用 `git commit -m "<message>"` 提交
```

### frontmatter 字段

| 字段 | 必须 | 说明 |
|------|------|------|
| `name` | 是 | 技能名称 |
| `description` | 是 | 描述 |
| `when-to-use` | 是 | 提示 Agent 何时自动使用（hint） |
| `user-invocable` | 否 | 是否可通过 `/name` 手动调用（默认 true） |
| `allowed-tools` | 否 | 逗号分隔的允许工具列表 |

### 模板变量

| 变量 | 说明 |
|------|------|
| `$ARGUMENTS` 或 `${ARGUMENTS}` | 用户传入的参数 |
| `${SKILL_DIR}` | 技能文件所在目录的绝对路径 |

### 调用方式

**手动调用**（REPL）：
```
/commit              # 无参数
/commit --amend      # 带参数
/review src/main.py  # 带参数
```

**自动调用**（Agent 通过 skill 工具）：
```json
{
  "name": "skill",
  "parameters": {
    "name": "commit",
    "arguments": "--amend"
  }
}
```

### 执行模式

| 模式 | 说明 |
|------|------|
| `inline` | 将技能提示注入当前对话上下文（默认） |
| `fork` | 创建隔离的子 Agent 执行，不污染主对话 |

### 内置技能示例

项目 `.forgecc/skills/` 目录预配置了：
- **commit**：分析 git diff 生成 Conventional Commits 格式的提交消息
- **review**：代码审查，关注安全、性能、可维护性

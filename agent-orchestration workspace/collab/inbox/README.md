# collab/inbox — 文件信箱协议

> 位于 `agent-orchestration workspace/collab/inbox/`；证据写主工作区 `agent-orchestration workspace/artifacts/<task>/`。

- 目录：`codex/`、`dsh/`、`claude/`、`human/`；消息是文件，固定 YAML 头。
- 一条消息一件事；禁贴大段日志与密钥；细节放 `artifacts/<task>/` 并给路径。
- 类型：`handoff` / `question` / `fix_request` / `report` / `escalate`。
- question 2 小时无答复 → 升级人类。

```markdown
---
id: M-0001
from: codex
to: orchestrator
task: T-001
type: handoff
round: 1
status: done
refs: [agent-orchestration workspace/collab/cards/T-001.md]
---
branch: codex/T-001
commit: <sha>
files: []
cmd: "<命令>::0::agent-orchestration workspace/artifacts/T-001/selfcheck.log"
cwd: agent-orchestration workspace/worktrees/codex/T-001
risks: []
verifier_entry: "<验证入口>"
unfinished: []
```
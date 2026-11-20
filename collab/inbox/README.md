# collab/inbox — 文件信箱协议

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
refs: [collab/cards/T-001.md]
---
branch: codex/T-001
commit: <sha>
files: []
cmd: "<命令>::0::artifacts/T-001/selfcheck.log"
cwd: worktrees/codex/T-001
risks: []
verifier_entry: "<验证入口>"
unfinished: []
```
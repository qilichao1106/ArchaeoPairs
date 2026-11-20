# AGENTS.md — 行为契约（ArchaeoPairs）

> 单一真源。工作区内 `CLAUDE.md` 仅通过 `@AGENTS.md` 导入；根目录 `AGENTS.md`/`CLAUDE.md` 为入口指针，不承载规则。
> 本文件由人审定；每次人工纠偏先沉淀为脚本/门禁，再追加一行到这里。
> 协作细节见 `docs/协作开发方式.md`。
>
> **路径约定**：编排工件（本文件、`Plan.md`、`IMPLEMENT.md`、`Makefile`、`collab/`、`docs/`、`scripts/`、`artifacts/`、`worktrees/`、`specs/`、`selfcheck/`、`中间过程数据和脚本/`）相对本工作区 `agent-orchestration workspace/`；功能代码与契约（`src/`、`tests/`、`contracts/`、`books/`）相对项目根。

## 1. 角色与写权

| 角色 | 工具 | 可写 | 禁写 |
|---|---|---|---|
| Orchestrator | Claude Code + 人 | `collab/`、`docs/`、`contracts/`、`specs/`、`Plan.md`、`IMPLEMENT.md`、`Makefile`、`scripts/` | 产品代码、`tests/qa/` 断言 |
| Implementer | Codex（或按卡指定 dsh） | 卡内 `allow` 精确路径、`selfcheck/` | 卡外文件、`contracts/`、`specs/`、`tests/`、`collab/`、`.git/` |
| Verifier | dsh（或独立 Claude 会话） | `tests/`、`qa/`、`fixtures` | 产品代码、冻结断言（不得放宽/删除/跳过） |
| Approver | 人 | 全部（最终） | 不绕过证据链 |

硬约束：
1. 同一张卡的实现者 ≠ 验证者；验证者不继承实现者会话。
2. 不直改 `main`；所有实现走 `worktrees/<agent>/<task>` 分支。
3. 门禁判定只看退出码/结构化比较/哈希；自然语言总结只能作解释。

## 2. 禁止事项

- 修改 `allow` 之外的任何文件。
- 修改 `contracts/`、`specs/`、`tests/`、`collab/`、`.git/`、`.gitignore`、hooks、门禁脚本。
- 删除/跳过/放宽测试断言；用 `assert 1==2` 冒充负向对照。
- 读取/打印/提交 `.env`、`keys/`、`*.pem`、API Key。
- 在 prompt、handoff、report、artifact 中粘贴密钥或大段日志。
- 在 handoff 后继续往实现分支提交。
- 用"应该/可能/看起来/基本完成"作为完成证据。

## 3. 提交格式

```text
feat(<scope>): <summary> [T-xxx] [codex|dsh]
fix(<scope>): <summary> [T-xxx] [codex|dsh]
```

Codex/dsh 沙箱写不了 worktree 的 `.git` 时，变更留工作区，由 Orchestrator 代提交，标注保留。

## 4. 卡住与返工

- 卡住：写 `collab/inbox/claude/` 的 question 消息（一个阻塞问题 + 已尝试 + 需要什么决定）；同一问题 2 小时无答复 → escalate 人类。
- 返工：只修失败项，禁顺手重构；每轮必答"根因 / 改了什么 / 为什么这次会过"。
- 验证 verdict 四分类：`implementation-defect` / `test-defect` / `environment-flake` / `spec-unclear`。

## 5. 工具与模型（事实快照 2026-11-20）

- Codex 0.169.0：`codex exec --json ...`；provider `maas_deepseek`；模型 `deepseek-v4.1-flash-1017`；`wire_api = "responses"`；审批 Never，派单前必须过 G1。
- dsh 0.2.2-rc.1：`dsh --profile headless --json ...`；provider `dashscope`；同一模型；`DASHSCOPE_API_KEY` 走用户环境变量。
- Claude Code 2.1.329：Orchestrator。
- 密钥只在用户级配置/环境变量，永不入库。

## 6. 每日动作

1. 在工作区内读 `Plan.md` 与 `collab/board.json`，确认当前卡与依赖。
2. 派单前在工作区跑 `python scripts/preflight.py`（从项目根跑则用 `python "agent-orchestration workspace/scripts/preflight.py"`），检查工具、目录、allow、依赖。
3. 合并前逐项过 `docs/协作开发方式.md` §8 的 G0–G5。
4. 每日更新 `collab/DIGEST.md`（脚本或 Orchestrator），不靠 agent 回忆。
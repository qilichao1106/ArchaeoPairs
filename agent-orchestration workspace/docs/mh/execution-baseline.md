# 执行基线（L0 轻量档）

> 本基线是项目排布的唯一登记处；行为契约见 `AGENTS.md`，协作细节见 `docs/协作开发方式.md`。
> 新增路径/角色先在此登记，再进 AGENTS.md。未登记的路径默认谁都不许写。
>
> **路径约定**：编排工件（`AGENTS.md`、`Plan.md`、`IMPLEMENT.md`、`Makefile`、`collab/`、`docs/`、`scripts/`、`artifacts/`、`worktrees/`）相对 `agent-orchestration workspace/`；功能代码与测试（`src/`、`tests/`、`contracts/`、`specs/`、`selfcheck/`、`books/`、`out/`）相对项目根。

## 1. 角色与 RACI

| 活动 | Orchestrator（Claude+人） | Implementer（Codex） | Verifier（dsh） | Approver（人） |
|---|---|---|---|---|
| AC/计划 | R/A | C | C | A |
| 任务卡 | R/A | I | I | C |
| 产品代码 | C | R/A | I | I |
| 测试断言 | I | I | R/A | C |
| 契约/基线 | R/A | I | C | A |
| 合并 | R/A | I | C | I |
| 例外/欠账 | R | I | I | A |

## 2. 路径写权

见 `AGENTS.md` §1 与 `docs/协作开发方式.md` §4。产品代码按卡 `allow` 精确路径；`contracts/`、`specs/`（项目根）与 `collab/`（工作区）归 Orchestrator；`tests/`、`qa/`（项目根）归 Verifier。

## 3. 卡模型与预算

字段见 `docs/协作开发方式.md` §5。默认 `max_files: 10`、`max_lines: 400`、`max_depth: 0`、`max_rounds: 3`、`budget: {tokens: 200000, wall_minutes: 90}`。超限拆卡，不放宽。

## 4. 门禁与失败动作

G0 规范门 / G1 授权门 / G2 自检门 / G3 验证门 / G4 合并门 / G5 回归门，判定与失败动作见 `docs/协作开发方式.md` §8。门禁脚本变更须 Approver 签字。

## 5. 通信协议

文件信箱：`collab/inbox/<agent>/`，消息固定 YAML 头（id/from/to/task/type/round/status/refs）。一条消息一件事；禁贴大段日志与密钥。question 2 小时无答复升级人类。

## 6. 隔离与共享资源

一任务一 worktree：`worktrees/<agent>/<task>`；验证树从 `handoff.branch` 拉取。共享资源（数据目录、端口、缓存）在 `docs/mh/env.md` 登记占用；本阶段无并发写者。

## 7. 环境与晋级

开发环境：Windows 11 + Python 3.12 + git 2.53；工具版本与端点见 `docs/mh/env.md`。本阶段无部署目标；产物目录 `out/`（运行产物）与 `artifacts/`（证据）分离。

## 8. 待确认

- 产品设计冻结（M1）
- 图版像素根目录（`books/` 去留、`--media-root`）
- 轻量档自建 `scripts/collabctl.py` vs 引入 `mh` 内核（互斥）
- 是否引入 VLM 仲裁/质检
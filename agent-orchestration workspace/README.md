# agent-orchestration workspace

ArchaeoPairs 的**编排与协作工作区**。功能代码、测试、数据不在这里；这里只放流程、计划、任务卡、看板、证据与辅助脚本。

## 目录

```text
AGENTS.md              行为契约（单一真源；根目录 AGENTS.md 为入口指针）
CLAUDE.md              Claude Code 入口（@AGENTS.md）
Plan.md                里程碑与验收命令
IMPLEMENT.md           决策与偏差日志
Makefile               有 make 环境时的命令入口（本机无 make）
collab/                任务卡、信箱、看板、事件流、每日摘要、停线记录
docs/
  协作开发方式.md       L0 协作流程（角色/卡/门禁/闭环）
  mh/                  执行基线、环境台账
specs/                 AC 场景与 crosswalk
selfcheck/             实现者自检
中间过程数据和脚本/     中间数据、临时结果、辅助脚本
scripts/               preflight.py / doctor.cmd
artifacts/             证据（不入库）
worktrees/             隔离工作树（不入库）
```

## 路径约定

- **工作区内**：`AGENTS.md`、`Plan.md`、`IMPLEMENT.md`、`Makefile`、`collab/`、`docs/`、`specs/`、`selfcheck/`、`中间过程数据和脚本/`、`scripts/`、`artifacts/`、`worktrees/`。
- **项目根**：`src/`、`tests/`、`contracts/`、`books/`、`v1/`。

## 常用命令

```bash
# 在工作区内
python scripts/preflight.py          # 或 Windows: scripts\doctor.cmd

# 从项目根
python "agent-orchestration workspace/scripts/preflight.py"
```

## 状态

- L0 协作基线已建立，预检 47 项通过。
- 产品设计待冻结（M1）；冻结前不建产品卡。
- 详见 `docs/协作开发方式.md`、`Plan.md`、`collab/DIGEST.md`。
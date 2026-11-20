# ArchaeoPairs

考古报告器物图 Pair 数据构造项目。从结构化 XML 与图版像素中，为单件器物产出（器物号、图像、描述文本）三元组，并保留"器物↔图中序号↔器物号"映射台账。

## 当前状态

- **V1.0 设计待定稿**：四条工作线（多器物线图 / 单器物线图 / 单器物版图 / 其它不处理）。
- 旧实现（V0.5.x / V0.6）整体归档于本地 `v1/`，不入库；`books/` 为图版数据，不入库。
- 协作基线已建立：L0 档，Claude Code 编排、Codex 实现、dsh 独立验证。

## 目录

```text
AGENTS.md / CLAUDE.md     行为契约（CLAUDE.md 导入 AGENTS.md）
Plan.md / IMPLEMENT.md    里程碑与决策日志
docs/                     协作方式、执行基线、环境台账
collab/                   任务卡、信箱、看板、证据
contracts/ specs/         数据契约与 AC 场景（M1 冻结）
src/ tests/ selfcheck/    产品代码、冻结测试、实现者自检
scripts/preflight.py      派单前预检
```

## 快速开始

```bash
python scripts/preflight.py        # 检查工具/配置/目录基线
# Windows: scripts\doctor.cmd
```

## 协作要点

- 同一张卡的实现者 ≠ 验证者；门禁只看退出码/结构化比较/哈希。
- 一任务一 worktree；实现者只改卡内 `allow` 路径；验证者只写 `tests/qa/`。
- 详见 `docs/协作开发方式.md` 与 `AGENTS.md`。

## 模型与工具

- Codex 0.169.0 / dsh 0.2.2-rc.1 / Claude Code 2.1.329
- 统一模型：`deepseek-v4.1-flash-1017`（用户级配置，密钥不入库）
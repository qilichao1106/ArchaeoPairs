# ArchaeoPairs

考古报告器物图 Pair 数据构造项目。从结构化 XML 与图版像素中，为单件器物产出（器物号、图像、描述文本）三元组，并保留"器物↔图中序号↔器物号"映射台账。

## 当前状态

- **V1.0 管线已实现**：XML 摄入 → 五分类 → 文本映射 → 分割 → VLM OCR/字形网格序号 → ArtifactMap → 比例尺绑定 → 成图 → Pair/ledger 落盘；T-001–T-012 已合并，全量 **490 passed**。
- 四条工作线：多器物线图 L1 / 单器物线图 L2 / 单器物版图 L3 / 其它归档 L4。
- 真书冒烟：`万州瓦子坪 --limit 10` → 18 Pair / 18 PNG；其中 17 output、1 个 `no_text` 复核。
- 数据集字段与复核语义见 `agent-orchestration workspace/specs/dataset_card.md`；黄金样例见 `specs/golden_set.md`。
- 旧实现（V0.5.x / V0.6）整体归档于本地 `v1/`，不入库；`books/` 为图版数据，不入库。
- 协作基线：L0 档，Claude Code 编排、Codex 实现、dsh 独立验证。

## 工作区划分

**功能工作区（项目根）**

```text
src/                    产品代码
tests/                  冻结验收测试（Verifier 写）
contracts/              数据契约（产品代码直接消费，M1 冻结）
books/                  图版数据（不入库）
v1/                     旧版归档（不入库）
AGENTS.md / CLAUDE.md   入口指针，指向编排工作区契约
```

**编排工作区（`agent-orchestration workspace/`）**

```text
AGENTS.md / CLAUDE.md   行为契约单一真源
Plan.md / IMPLEMENT.md  里程碑与决策日志
collab/                 任务卡、信箱、看板、证据
docs/                   协作方式、执行基线、环境台账
specs/                  AC 场景（M1 冻结）
selfcheck/              实现者自检
中间过程数据和脚本/      中间数据、临时结果、辅助脚本
scripts/                preflight / doctor
artifacts/              证据（不入库）
worktrees/              隔离工作树（不入库）
```

## 快速开始

```bash
# 从项目根
python "agent-orchestration workspace/scripts/preflight.py"

# 或在编排工作区内
cd "agent-orchestration workspace"
python scripts/preflight.py
# Windows 也可用 scripts\doctor.cmd
```

## 运行

```bash
export DASHSCOPE_API_KEY=...   # 用户级环境变量，不入库

# 单本（默认 VLM OCR；--no-vl 回退 Paddle）
PYTHONPATH=src python -m archaeopairs.cli run-book \
  --book 万州瓦子坪 --out runs/万州瓦子坪

# 全量批跑（每本一个子进程，跳过已有 pairs.jsonl 的书）
python "agent-orchestration workspace/中间过程数据和脚本/batch_books.py" --workers 4

# 产物审计（垃圾图/重名/视图复用）
python "agent-orchestration workspace/中间过程数据和脚本/audit_run.py" runs/万州瓦子坪

# 批次汇总 / 逐本审计 / 复核原因
python "agent-orchestration workspace/中间过程数据和脚本/summarize_batch.py" runs/batch
python "agent-orchestration workspace/中间过程数据和脚本/audit_batch.py" runs/batch
python "agent-orchestration workspace/中间过程数据和脚本/review_report.py" runs/万州瓦子坪
```

## 协作要点

- 同一张卡的实现者 ≠ 验证者；门禁只看退出码/结构化比较/哈希。
- 一任务一 worktree；实现者只改卡内 `allow` 路径；验证者只写 `tests/qa/`。
- 详见 `agent-orchestration workspace/docs/协作开发方式.md` 与 `agent-orchestration workspace/AGENTS.md`。

## 模型与工具

- Codex 0.169.0 / dsh 0.2.2-rc.1 / Claude Code 2.1.329
- 统一模型：`deepseek-v4.1-flash-1017`（用户级配置，密钥不入库）
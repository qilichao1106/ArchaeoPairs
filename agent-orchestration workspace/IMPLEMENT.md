# IMPLEMENT — 决策与偏差日志

> 只追加，不覆盖。偏差必须带失效条件与影响范围。

## D-001 v1 归档，保留 books

- 日期：2026-11-20
- 决策：除 `books/` 与 `.git/` 外，旧项目内容全部移入 `v1/`；`data/` 一并归档。
- 原因：开始新方案，旧实现只作参考；books 是当前可见的图版数据。
- 影响：`v1/.venv` 路径失效，不再使用；旧 `.gitignore` 随 v1 归档，新根目录重建忽略规则。

## D-002 协作档位 L0 + C

- 日期：2026-11-20
- 决策：Claude 编排 / Codex 实现 / dsh 验证，WIP=1；不并行、不引入 mh 内核。
- 原因：单人评审带宽、强耦合视觉链路、尚无单 agent 基线。
- 升级条件：连续两波吞吐 > 单 agent、allow 可切分、人工介入 <3 次/日；否则维持 L0。

## D-003 模型与端点

- 日期：2026-11-20
- 决策：codex 与 dsh 统一使用 `deepseek-v4.1-flash-1017`；OpenAI 兼容端点走阿里云 MaaS
  `/compatible-mode/v1`；codex `wire_api = "responses"`（0.169 已移除 chat）。
- 密钥位置：codex 用户级 `~/.codex/config.toml`；dsh 使用 Windows 用户环境
  `DASHSCOPE_API_KEY`。均不入仓库。
- 验证：两端 `只回复 OK` 冒烟通过。
- 失效条件：端点或模型下线、codex 移除 responses、dsh 更换 provider 配置格式。

## D-004 产品设计待定稿

- 日期：2026-11-20
- 状态：项目根 `v1/docs/V1.0_四条工作线架构方案.docx` 为讨论起点，未冻结。
- 影响：M1 之前不建产品卡；只允许 M0 基线与探针卡。

## D-005 编排工作区独立

- 日期：2026-11-20
- 决策：编排/协作工件迁入 `agent-orchestration workspace/`；根目录保留 `src/`、`tests/`、
  `contracts/`、`specs/`、`selfcheck/`、`books/`、`中间过程数据和脚本/` 与两个入口指针。
- 原因：辅助代码与功能代码分离，根目录保持整洁；卡片/看板/证据与产品代码不混放。
- 影响：所有协作命令默认在 `agent-orchestration workspace/` 内执行；从项目根执行时给路径加前缀。
- 注：本条根目录清单已由 D-006 调整（`specs/`、`selfcheck/`、`中间过程数据和脚本/` 后续迁入工作区）。

## D-006 辅助工件二次归并

- 日期：2026-11-20
- 决策：`specs/`、`selfcheck/`、`中间过程数据和脚本/` 一并迁入工作区；`contracts/` 保留项目根
  （产品代码与测试直接消费）；根 `AGENTS.md` / `CLAUDE.md` 仅保留入口指针。
- 原因：辅助编排内容与功能代码彻底分离，同时不破坏产品对数据契约的 import。
- 影响：技术契约在根、验收辅助在工作区；路径约定同步更新到 AGENTS/协作方式/执行基线/README。

## D-007 需求边界对齐

- 日期：2026-11-20
- 决策：输入以 `books/<book>/data.xml + media` 为准；其余边界采用建议默认：
  - 一器物一图一 Pair（单图内）；跨图同器物各自成 Pair，不合并；
  - 无描述文本仍出 Pair，`description_text=null` + `no_text` + 复核；
  - 同一 `seq` 多器物共享同一图像资产；
  - L1 无比例尺报警复核；L2/L3 无尺允许并标记 `no_scale`；
  - 成图剥离序号数字，保留图旁说明文字与比例尺；
  - 未映射/缺视图一律 `unbound_*` + 复核，不猜测；
  - 交付 `PNG + pairs.jsonl + ledger.jsonl`。
- 产出：`specs/需求文档_V1.0.md` / `.docx`。
- 状态：草案，待人工评审冻结；冻结前不建产品卡。
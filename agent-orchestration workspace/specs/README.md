# specs/ — 需求、场景与 AC（唯一写者：Orchestrator）

## 当前工件

- `需求文档_V1.0.md` / `.docx`：需求正文与边界裁决（2026-11-20 边界已对齐，待人工评审冻结）。
- AC-01…AC-08 见需求文档 §8。

## 使用方式

- 需求冻结后，把每条 `R-xxx` 落为 WHEN/THEN 场景与 crosswalk：
  `需求 R → 场景 WHEN/THEN → AC → 任务卡 → 测试 nodeid`。
- 设计冻结前不建产品卡；只允许 M0 基线与探针卡。
- 协作流程见 `../docs/协作开发方式.md`；执行基线见 `../docs/mh/execution-baseline.md`。
- 需求文档变更须走 ADR/CR，不得由实现者直接改。
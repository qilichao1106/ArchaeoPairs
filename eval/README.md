# eval/ — 评测与选型实验位（P0 交付，当前占位）

规划内容（见方案 V0.2 §7/§9 与代码评估报告 P1 项）：

- `golden/golden.jsonl`：自建 golden set（100 图分层：case1 12 + case2 60 + 规则B 12 + 密集 8 + 彩板 8）与标注规范；
- `metrics.py`：配对 P/R、seq→id 准确率、IoU≥0.9 通过率、归组准确率、端到端可用率复算；
- 选型对照实验脚本与压测报告（编排 8 维 PoC、模型能力档对照），冻结结论回写 `config/selection_report.md`；
- VLM/SAM 录制回放 fixture（配合 `gateway.RecordingGateway` 的 replay）。

单元测试当前位于 `tests/`（21 用例，含附录C B1–B3 正则回归门禁）。

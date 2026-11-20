# 需求 → AC → 测试 Crosswalk（V1.0）

> 需求基线：`需求文档_V1.0.md`（2026-11-20 冻结）。
> 测试建立后，把 `测试 nodeid` 与 `commit/artifact` 填满；任取一条 AC，一分钟内能定位。

## 需求分组 → AC

| 需求组 | 关键条款 | AC |
|---|---|---|
| 输入契约 R-IN-01–10 | books 布局、XML 角色、缺失处理、五分类路由 | AC-01 |
| 器物身份 R-ID-01–06 | 器物号归一、后缀保留、跨书隔离 | AC-02、AC-07 |
| 映射 R-MAP-01–08 | 四类基数、优先级、unbound、同号/多视图/跨图 | AC-02、AC-06 |
| 比例尺 R-SCALE-01–05 | 前缀组、共享尺、无前缀多尺、无尺分流 | AC-03 |
| 四条工作线 R-L1–L4 | L1 全链、L2/L3 直通、L4 归档 | AC-01、AC-04 |
| 输出 R-OUT-01–08、R-IMG-01–10、R-NAME-01–06 | PairRecord、成图、命名、跨图索引 | AC-04、AC-05、AC-07 |
| 质量 R-QC-01–08 | 自动/复核分流、VLM 边界、复核队列 | AC-06、AC-08 |
| 运行 R-OPS-01–08 | 批处理、幂等、离线、许可 | AC-08 |
| 数据 R-DATA-01–04 | PNG+JSONL+ledger、阶段产物、可复现 | AC-04、AC-08 |

## AC 台账

| AC | 内容 | 测试 nodeid | 证据 | 状态 |
|---|---|---|---|---|
| AC-01 | 四条工作线路由，L4 零 Pair | `tests/qa/T-002/` | T-002 | partial |
| AC-02 | 1:1 / N:1 / 1:N / N:M 映射正确 | `tests/qa/T-003/` | T-003 | partial |
| AC-03 | 比例尺三级绑定与来源落盘 | `tests/qa/T-004/` | T-004 | partial |
| AC-04 | L2/L3 整图直通、01 命名 | 待建 | 待建 | gap |
| AC-05 | 成图白底/纯平移/留白/比例尺置底 | 待建 | 待建 | gap |
| AC-06 | 未映射/缺视图进入 unbound 并复核 | 待建 | 待建 | gap |
| AC-07 | 命名规则（图号、冒号、_N、后缀） | 待建 | 待建 | gap |
| AC-08 | 全量回归 + 负向对照 | 待建 | 待建 | gap |

状态枚举：`covered` / `partial` / `failed` / `gap` / `out_of_scope`。只有测试进主干且通过才可标 `covered`。

## T-001 契约测试说明

- T-001（commit `04c1109`）只验证 **JSON Schema 形状**：14 passed。
- 不证明 AC-02 的映射行为，也不证明 AC-07 的命名输出；二者仍为 `gap`，待产品卡。
- 证据：`selfcheck/T-001/pytest.log`；copy-proof 指向 `worktrees/dsh/T-001`。

## T-002 验收说明

- 实现 `e2618b7`（codex）；测试 `6d80d95`（dsh）。
- dsh 独立执行：52 passed；负向对照（图题优先注入）→ 1 failed，恢复 → 52 passed；全量回归 66 passed。
- AC-01 标 `partial`：五分类→四线映射已覆盖；流水线实际路由与 L4 零 Pair 待后续卡。
- 证据：`tests/qa/T-002/`；copy-proof 指向 `worktrees/dsh/T-002`。

## T-003 验收说明

- 实现 `e23e67c` + `3c6eeee`（codex/编排侧例外修复）；测试 `f3738cb`（dsh）。
- dsh 独立执行：69 passed；负向对照（区间 bug 注入）→ 2 failed，恢复 → 69 passed；全量回归 135 passed。
- AC-02 标 `partial`：文本层四类基数与冲突已覆盖；视图/比例尺映射待后续卡。
- 证据：`tests/qa/T-003/`；copy-proof 指向 `worktrees/dsh/T-003`。

## T-004 验收说明

- 实现 `cb82f45`（codex）；测试 `0ede96d`（dsh）。
- dsh 独立执行：59 passed；负向对照（不重试 429/5xx）→ 5 failed，恢复 → 59 passed；全量回归 194 passed。
- 真实 VLM 冒烟：文本返回 OK；`image11.jpg` 图片 OCR 返回带 bbox 的 seqs JSON（usage/latency 可观测）。
- AC-03 标 `partial`：VLM OCR/比例尺读取能力已覆盖；三级绑定与视图匹配待后续卡。
# 报警码契约（E001–E007）

> 需求 V1.0 §6；硬报警一律 `PENDING_REVIEW`，**不输出 PNG**，携带映射表与证据。

| 报警 | 触发条件 | 处理 | 证据字段 |
|---|---|---|---|
| E001 | 图注声明某 `seq_id`，图面找不到对应视图 | 复核，不出图 | `unbound_seqs[].seq_id`、`artifact_ids` |
| E002 | 图面存在带 `seq_id` 的视图，图注无对应声明 | 复核，不出图 | `unbound_views[].seq_id` |
| E003 | 多个带号比例尺无法与任一线图序号对应 | 复核，不出图 | `scale_id`、`prefix_nos` |
| E004 | 比例尺无号且全图存在多把尺 | 复核，不出图 | `scale_id`、`scale_bindings` |
| E005 | 多器物但图注无序号列表 | 复核，不出图 | `case_type=seq_missing` |
| E006 | 共享基准线导致掩膜残缺 | 复核，不出图 | 视图 `bbox`、`incomplete` |
| E007 | 其它硬约束/证据不足（含 VL 决定性门未决） | 复核，不出图 | `conflicts`、VL 证据 |

## 处置规则

1. 任一 E 码 → `ArtifactMap.status = pending_review`、`PairRecord.status = review`，不写 `image_path` 成品。
2. 复核队列至少包含：`book_id`、`figure_id`、`artifact_id`（可空）、`seq_ids`、`alarms`、`mapping` 快照、原图路径、候选图路径。
3. 人工修正 `seq→artifact` 或 `mask→artifact` 后，从映射阶段重入；不重跑分割。
4. 禁止自动回退/猜测；E 码不得被配置关闭。
5. 无文本、无比例尺等软问题不升 E 码，使用 `quality_flags`（`no_text` / `no_scale` / `long_text`）。
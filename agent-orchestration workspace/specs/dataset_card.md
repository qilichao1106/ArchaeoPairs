# 数据集说明（ArchaeoPairs V1）

## 目录

```text
runs/<run>/
  pairs/<原图名称>_[seq|01]_<器物号>.png   单器物成图
  pairs.jsonl                             每行一个 PairRecord
  ledger.jsonl                            每图/每单元的映射台账与阶段证据
```

- L1 多器物线图：`seq` 为图中序号（同号多视图用逗号串）。
- L2 单器物线图 / L3 单器物版图：`01`。
- 器物号中的 `:` 在文件名里写作 `-`；后缀 `a/b`、`-1` 按 R-ID-06 保留。
- 同名冲突由 `dedup_name` 追加序号，pairs.jsonl 中以 `image_path` 为准。

## PairRecord 关键字段

| 字段 | 含义 |
|---|---|
| `book_id` / `figure_id` | 书与图（XML 中的 figure） |
| `artifact_id` | 归一化器物号 |
| `artifact_name` | 图注/图题中的器物名称，可空 |
| `figure_number` | 图号/图版号 |
| `source_role` | `line` / `plate` |
| `image_path` | 相对 run 目录的 PNG 路径 |
| `description_text` / `text_length` | 正文描述全文与字数 |
| `provenance.mapping` | artifact / seq / view / scale 的四路映射、置信度、来源 |
| `quality_flags` | `no_text` / `no_scale` / `long_text` / `shared_image` 等 |
| `status` | `output` / `review` |

`provenance.art_source` 记录器物号来自 `figure_note` / `caption` / `text` / `manual`。

## 复核语义

- `status=review`：该 Pair 需要人工确认；原因看 `quality_flags` 与 ledger 的 `alarms/conflicts/unbound`。
- 无 `no_text` 以外的图：L1 若存在未绑定视图/序号、冲突或 Unit 污染，整图成图会留空（`image_path` 为空），避免发布错误图；ledger 保留完整失败证据。
- `no_scale`：未绑定图形比例尺；L2/L3 允许，L1 通常伴随复核。
- `shared_image`：同一 PNG 被多个 Unit 合法共享（1:N 同号多器物）。

## 批次审计

```bash
python "agent-orchestration workspace/中间过程数据和脚本/audit_run.py" <run>
python "agent-orchestration workspace/中间过程数据和脚本/review_report.py" <run>
python "agent-orchestration workspace/中间过程数据和脚本/audit_batch.py" runs/batch
```

`audit_run.py` 检查：PNG 可读/非垃圾、名称含器物号、名称唯一、L1 视图/序号不跨器物复用（合法共享除外）。
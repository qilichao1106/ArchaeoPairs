# backlog — P1/P2 与范围外需求

> 不插队；新需求走 CR，不接受"顺手做了"。

## P0（当前）

- 契约冻结：`contracts/artifact_map.schema.json`、`pair_record.schema.json`、`alarms.md`、`naming.md`。
- 冻结后：首批实现卡（输入解析与四线分类 → L1 纵切）。

## P1

- 轻量档 `scripts/collabctl.py`（建卡/派单/看板/消息/合并）。
- 黄金样例集与回归套件。
- VLM 仲裁/质检是否引入。

## P2 / 范围外

- 多器物彩图拆分。
- 跨图 / 跨报告 artifact 聚合。
- Web 看板、消息队列、调度平台（明确不做）。
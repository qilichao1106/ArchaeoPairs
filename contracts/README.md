# contracts/ — 数据契约（唯一写者：Orchestrator）

> 状态：V1.0 草案，随需求 V1.0（2026-11-20 冻结）落定；待人工签字后标记 `frozen`。
> 实现者只读；代码与契约冲突默认代码错；破坏性变更走 CR/ADR。

## 文件

| 文件 | 内容 | 消费者 |
|---|---|---|
| `artifact_map.schema.json` | 单图映射表：Unit / ScaleBinding / unbound / conflicts / alarms | 流水线、台账、复核 |
| `pair_record.schema.json` | Pair 输出：artifact 元数据、image_path、text、mapping provenance、quality_flags | 数据集、下游转换 |
| `alarms.md` | E001–E007 触发条件、处置、证据字段 | 质检、复核队列 |
| `naming.md` | 命名规则与示例 | 成图、去重、下游引用 |

## 校验

```bash
python contracts/validate.py   # schema metaschema + 样例 + 负向对照
```

`tests/contracts/`（Verifier 写）建立后，增加冻结验收测试；`contracts/validate.py` 保留为编排者自检。

## 变更

- `artifact_id` / `seq_ids` / `scale_ids` / 命名规则的变更必须走 ADR。
- 新增字段先改 schema，再改实现与测试；不得先写代码后补契约。
- 契约冻结后，实现者不得直接修改本目录。
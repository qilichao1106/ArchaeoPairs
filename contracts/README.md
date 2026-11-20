# contracts/ — 数据契约（唯一写者：Orchestrator）

M1 设计冻结时落地以下契约（JSON Schema + pydantic 模型 + fixtures）：

| 契约 | 内容 |
|---|---|
| `artifact_map.schema.json` | 四条工作线共用映射表：units / unbound_* / conflicts / alarms |
| `pair_record.schema.json` | Pair 输出：artifact_id / image_path / description / mapping provenance |
| `alarms.md` | E001–E007 触发条件与处置 |
| `naming.md` | 原图名_[seq|01]_器物号、冒号归一、_N 去重、后缀保留 |
| `fixtures/` | 契约夹具（写权归 Verifier） |

纪律：实现者只读；代码与契约冲突默认代码错；破坏性变更走 CR/ADR。
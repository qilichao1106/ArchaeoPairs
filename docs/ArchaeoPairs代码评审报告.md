# ArchaeoPairs 代码评审报告

- 评审对象：`src/archaeopairs/`、`tests/`、`config/`、`ddl.sql`、`README.md`
- 评审依据：《考古报告图文Pair数据构造_多智能体方案_V0.1.docx》
- 评审日期：2026-08-12
- 评审性质：方案落地合规性审查 + 代码资产质量审计

## 1. 总体结论

当前仓库是一套可运行的 P0 mock 骨架，不是 V0.1 方案的可交付实现。方案中最核心的“硬约束报警、双源三链融合、Loop Engineering、人工复核闭环、真实成图/命名/存储”都还没有真正落地。

现有测试主要证明 mock happy path 和图拓扑存在，不能作为“方案已覆盖”的证据。

## 2. 验证结果

| 检查项 | 结果 |
| --- | --- |
| `pytest -q --cov=archaeopairs` | 31 项通过，覆盖率 81% |
| `ruff check src tests` | 通过 |
| `mypy src` | 5 个类型错误 |
| `storage/db.py`、`schemas/__init__.py` | 覆盖率 0% |
| `s3_text.py` | 覆盖率 17% |

`mypy` 错误位置：

- `src/archaeopairs/schemas/__init__.py:31`：`ModelMetaclass` 无 `model_json_schema`
- `src/archaeopairs/parsers/s1_xml.py:65`：列表元素类型不匹配
- `src/archaeopairs/agents/s5.py:44`：`case_type` 类型不匹配
- `src/archaeopairs/orchestration/graph.py:16`：`add_node` 类型不匹配
- `src/archaeopairs/cli.py:52`：缺少类型注解

## 3. 关键问题（按严重度排序）

### 3.1 P0：硬约束报警体系基本未实现

方案要求 E001–E007 七类异常报警，触发即 `PENDING_REVIEW`、禁止输出 PNG。当前代码仅有 `AlarmError` 占位，未接入业务逻辑。

- `src/archaeopairs/errors.py:118`：只定义了 `AlarmError`，代码体为 E001 占位。
- `src/archaeopairs/agents/s6.py:8`：只检查 `mask_rle` 是否存在，没有比例尺三级归属、轮廓完整、共享基准线等报警。
- `src/archaeopairs/agents/s8.py:18`：遇到无器物号的 mask 直接 `continue`，没有触发报警。
- `src/archaeopairs/agents/s10.py:9`：只处理 `seq_missing` 和迭代上限，未处理 E001–E007。
- `src/archaeopairs/orchestration/graph.py:16`：图没有统一异常拦截，`HardConstraintError` 会直接中断图，而不是转 `PENDING_REVIEW`。

结论：方案 §12 硬约束追溯矩阵中的“已覆盖”状态不成立。

### 3.2 P0：多个核心智能体节点是空壳

- `s1_index` 只返回状态，没有做 XML 摄入、契约校验、无器物号排除。
  - `src/archaeopairs/agents/s1.py:7`
- `s3_text` 实现了正文切分决策树，但 S3 节点没有调用它，链②实际没有进入管线。
  - `src/archaeopairs/agents/s3.py:8`
  - `src/archaeopairs/parsers/s3_text.py:15`
- `s7_plate` 只是按 `figure_id` 生成一条 Pair，没有图版标题提取、条目映射、`plate_scene` 区分。
  - `src/archaeopairs/agents/s7.py:7`
- `s10_review` 没有 Label Studio 集成、webhook、幂等回写、resume 逻辑。
  - `src/archaeopairs/agents/s10.py:9`

### 3.3 P0：S5 不是真正的融合仲裁

`src/archaeopairs/agents/s5.py:22` 只使用 `note_items` 是否为空和链存在性判断，存在以下问题：

- 没有比较 `seq_annotations` 与图注序号是否一致。
- 没有 OCR 序号冲突检测。
- 没有按降级矩阵决定 `seq_missing`。
- 图注为空时无条件判 `seq_missing`，会误杀“正文+OCR”双链可降级场景。
- `split_same_seq` 使用 `dict[str,str]`，无法表达“同一 seq 对应多个 artifact_id”，`zip` 会截断数据。

### 3.4 P0：Loop Engineering 没有真正闭环

- S6 每次都用空 `prompts=[]` 分割，没有消费 S9 的指导信号。
  - `src/archaeopairs/agents/s6.py:8`
- S9 没有实现“连续两轮无改善”收敛判断，也没有逐级升级。
  - `src/archaeopairs/agents/s9.py:9`
- 路由回环存在，但“针对性修正”没有实现。

### 3.5 P0：S8 的拆 Pair 与命名不符合规范

- `seq_to_artifact` 为 `dict[str,str]`，无法表达同号多器。
  - `src/archaeopairs/agents/s5.py:35`
- S8 按第一个 artifact 组装，同号拆 Pair 数据会丢失。
  - `src/archaeopairs/agents/s8.py:18`
- 输出文件名没有按图题提取“图号”，没有重名 `_N` 去重，没有实际成图。
  - `src/archaeopairs/agents/s8.py:32`

### 3.6 P1：存储层没有被管线使用

- `cli.py` 只使用 LangGraph SqliteSaver，未写 `FigureState/PairRecord/DiagnosticReport/ReviewTask`。
  - `src/archaeopairs/cli.py:47`
- SQLAlchemy 模型缺少 `diagnostic_reports` 表，与 DDL 不一致。
  - `src/archaeopairs/storage/db.py:23`
- 没有 claim、原子写、对象存储、批量恢复。

### 3.7 P1：模型网关缺少关键语义

- 没有超时、指数退避、4xx 不重试、60 秒熔断恢复。
- 没有把 `CostCapExceeded` 映射到 `PENDING_REVIEW`。
- `Gateway.stats.calls` 和 `cost_by_figure` 无界增长。
  - `src/archaeopairs/gateway.py:33`

## 4. 六维度逐项审查

### 4.1 方案一致性

严重偏离。方案中的 18 条硬约束大多只有字段名或注释，没有可执行断言；S1/S3/S5/S6/S7/S8/S9/S10 均存在“有节点、无能力”的情况。代码未同步更新方案文档，也未建立“方案反哺”差异清单。

### 4.2 架构设计与扩展性

方向正确，落地不足：

- 正向：`capability` 协议、`Services` 依赖注入、NoteParser 注册表、节点与路由分离。
- 缺口：存储、Webhook、成图、迁移工具、任务队列均未接入；缺少策略模式实现比例尺三级和分割指导信号。

### 4.3 代码可读性与可维护性

- 正向：文件名、类名、docstring 总体清楚，单文件很短。
- 缺口：缺少日志与全局异常上下文；多处注释声称“对齐方案”但实际行为未对齐，容易误导后续开发。

### 4.4 健壮性与错误处理

- 没有全局异常处理。
- 没有事务边界。
- 没有输入校验。
- `LocalObjectStore` 的 key 直接拼进路径，存在路径穿越风险。
  - `src/archaeopairs/storage/object_store.py:15`

### 4.5 性能与资源消耗

当前没有真实 SQL/图片处理，性能风险未暴露；但 `Gateway.stats.calls`、`cost_by_figure` 和 `cli.py` 的 `pair_records` 都是无界内存累积，16k 图规模下会放大。

### 4.6 安全合规

- 正向：未发现硬编码密钥，SQLAlchemy 参数化避免了 SQL 注入，无 Web 页面也就无明显 XSS 面。
- 缺口：没有权限控制、无 webhook 鉴权、无 LS 脱敏、无内容合规处理，方案要求的生产安全项基本未落地。

## 5. 测试缺口

- 硬约束测试只覆盖“mask 必须带 RLE”，没有 E001–E007。
  - `tests/test_hard_constraints.py:10`
- `split_same_seq` 只断言 `case_type`，没有断言最终 Pair 数量和 artifact_id。
  - `tests/test_s8_assemble.py:31`
- 没有 S10 interrupt/resume 测试。
- 没有网关熔断/成本帽测试。
- 没有比例尺三级归属测试。
- `storage`、`schemas`、`s3_text` 覆盖率过低。

## 6. 建议整改顺序

1. 先补 E001–E007 报警检测与全局异常路由，保证“报警即 `PENDING_REVIEW`、禁输出 PNG”。
2. 将 S1 的 XML 摄入、契约校验、无器物号排除接入图节点。
3. 将 `s3_text` 接入 S3，并完善多锚点切分。
4. 重构 `FusedMapping`，支持 `seq -> artifact_ids` 多值映射，修复同号拆 Pair。
5. 实现 S6 消费 DiagnosticReport 的针对性修正，并实现 S9 收敛判定。
6. 接入存储层、对象存储、Label Studio webhook 与幂等回写。
7. 补齐关键测试，尤其硬约束、路由枚举、checkpointer resume、网关降级。

## 7. 未决问题

- 本次评审以 V0.1 docx 为准；仓库 `.workbuddy/tmp/V0.1.txt` 内容显示为 V0.5，建议清理或统一版本命名。
- 当前目标是否为“P0 mock 骨架”还是“V0.1 可验收实现”？建议在 README 或方案中明确验收边界。

# ArchaeoPairs 代码评审报告（第二轮）

- 评审对象：优化后的 `src/archaeopairs/`、`tests/`、`config/`、`ddl.sql`
- 评审依据：《考古报告图文Pair数据构造_多智能体方案_V0.1.docx》
- 评审日期：2026-08-12
- 评审性质：方案落地合规性复查 + 代码资产质量审计

## 1. 总体结论

与第一轮相比，代码质量有实质提升：从“空壳骨架”进步为“可运行的 P0 mock 管线”。E001–E007 报警体系、命名规范、对象存储、网关重试/熔断、存储落库、测试覆盖等都有明显补齐。

但当前仍不能视为 V0.1 方案的可验收实现。核心问题集中在：降级链没有真正走通、S9 不收敛判定可能导致无限回环、比例尺三级归属未接入主管线、S8 仍存在静默丢数据、S7 依赖 mock ground、并发 claim 不原子。

## 2. 验证结果

| 检查项 | 结果 |
| --- | --- |
| `pytest --collect-only` | 58 项测试 |
| `pytest -q --cov=archaeopairs` | 全量通过，覆盖率 92% |
| `ruff check src tests` | 失败，6 个可修复问题 |
| `mypy src` | 失败，5 个类型错误 |

`ruff` 问题集中在 `cli.py`、`storage/__init__.py`、`tests/conftest.py`、`tests/test_storage.py` 的 import 排序和未使用 import。

`mypy` 仍报错：

- `schemas/__init__.py:31`
- `parsers/s1_xml.py:65`
- `agents/s5.py:66`
- `agents/s8.py:45`
- `orchestration/graph.py:16`

## 3. 关键问题（按严重度排序）

### 3.1 P0：S9 不收敛判定未传给路由，可能无限回环

`src/archaeopairs/agents/s9.py:26` 计算了 `no_improve`，但只在“无改善”时停止增加 `iteration`；`routing.route_supervise` 只看 `iteration >= max_iteration`，没有读取 `no_improve` 状态。

实测恒定缺陷场景：

```text
iteration=1 history=[1]      route=> segment
iteration=1 history=[1,1]    route=> segment
iteration=1 history=[1,1,1]  route=> segment
```

即“连续两轮无改善”后仍会继续回环，直到 LangGraph 递归上限或外部终止。方案 §4.9.2 的“提前转 PENDING_REVIEW”没有落地。

### 3.2 P0：降级链被直接转复核，没有真正走链②+链③

`src/archaeopairs/agents/s5.py:64` 将图注缺失且有链②/链③的场景标记为 `degraded=True`，但 `src/archaeopairs/orchestration/routing.py:29` 把所有 `degraded` 直接路由到 `bridge_review`。

方案 §3.6 要求“正文+OCR”双链可降级处理并置信封顶 0.70，而不是直接排除。当前实现会人为扩大 PENDING_REVIEW 范围，无法处理 `note稀疏型` 报告。

### 3.3 P0：比例尺三级归属仍未接入主管线

`src/archaeopairs/agents/alarms.py` 实现了 `assign_scales()`，但 S5/S6/S8 均未调用它。S6 只消费 `action_params.points`，没有读取 `scale_annotations`、没有将比例尺分配给 mask、没有共享比例尺复制、没有旋转校正。

因此方案第 5、6、7 条硬约束仍是测试级覆盖，不是管线级落地。

### 3.4 P0：S8 对无映射 mask 静默丢弃

`src/archaeopairs/agents/s8.py:44` 中，`seq_to_arts.get(str(m.get("seq")), [])` 为空时不会产生 Pair，也不会报警，最终仍返回 `ASM_VALIDATED`。

实测：

```text
masks=[seq=2, 无映射] records=[] status=ASM_VALIDATED alarms=None
```

这违反“无映射 mask 不静默丢弃（转复核）”的注释，也违反“报警即停、禁猜测配对”的硬约束。

### 3.5 P1：正文段落被全量注入每个 figure，文本关联越界

`src/archaeopairs/cli.py:64` 将整本 `body_paras` 放入每个 figure 的初始 State；S3 对整本书做 `s3_text.split_body`，S8 再按 `artifact_id` 全量查找描述文本。

这会导致某个 Pair 的描述文本可能来自全书任意段落，而不是该图/该器物对应的正文。方案要求“按器物号切分的该器物专属描述段”，当前实现没有按 figure 或图引用做作用域过滤。

### 3.6 P1：S7 依赖 mock ground，plate_scene 分支不可达

`src/archaeopairs/agents/s7.py:22` 从 `svc.ground` 取 artifact_id，而 `ground` 是 P0 mock 专用数据，生产实现不存在。

同时 `s1_xml.py` 将所有“图版/圖版”标题都判为 `plate_artifact`，`route_classify` 又对 `plate_scene` 直接返回 END，因此 S7 的 `plate_scene` 分支在真实链路中不可达。方案要求的“不得仅凭图版关键词判 plate”仍未实现。

### 3.7 P1：claim 不是原子认领

`src/archaeopairs/storage/db.py:84` 使用 `SELECT` 后更新，不是 `SELECT FOR UPDATE SKIP LOCKED`，两个 Worker 可能同时读到 `INIT` 并同时认领同一 figure。

### 3.8 P1：网关“录制回放”只记录元信息，不记录请求/响应

`src/archaeopairs/gateway.py:94` 的 `recording()` 只导出调用时间与 key，不包含输入、输出、prompt、模型响应，无法用于真正的回放复算。方案的 §5.8 录制回放能力未完整落地。

另外网关没有实现 Worker 配额限流，只实现了成本帽和熔断。

### 3.9 P1：S3 多锚点切分仍是“整段共享”

`src/archaeopairs/parsers/s3_text.py:29` 对多锚点段落为每个锚点复制整段文本，没有按“标本X:1, ...”边界真正切分，也没有写入 `figure_refs`、标本号标记或 LLM 二次确认。

### 3.10 P1：关键测试仍缺失

- 没有 S9 不收敛后路由到 PENDING_REVIEW 的回归测试。
- 没有降级链真正分割并输出的端到端测试。
- 没有 S8 无映射 mask 必须报警的测试。
- 没有 assign_scales 在 S6 主管线中的集成测试。
- 没有 S7 不依赖 ground 的条目映射测试。
- claim 测试只验证单进程，不验证并发原子性。

## 4. 六维度逐项摘要

### 4.1 方案一致性

比第一轮明显改善，E001–E007、命名、存储、网关等已有代码映射；但降级矩阵、比例尺三级、Loop Engineering 收敛、无映射 mask 报警仍存在“字段有、链路无”或“计算结果未使用”的情况。

### 4.2 架构设计与扩展性

`Services` 注入、能力协议、ReviewBridge、Compositor、ObjectStore 都是良好的扩展点。主要问题是 `ground` 作为 mock 数据直接注入 S7/S8，生产链路存在“测试数据渗入业务代码”的耦合。

### 4.3 代码可读性与可维护性

命名和模块划分总体清晰，注释能说明业务意图。但 `s8.py` 的“无映射 mask 不静默丢弃”注释与实际行为冲突，`routing.py` 的“降级→直接复核”与方案降级矩阵冲突，需要修正注释或实现。

### 4.4 健壮性与错误处理

节点 guard 已能捕获报警/硬约束/成本帽，但其他 `ArchaeoPairsError` 仍会直接中断图。`claim_figure` 非原子，webhook 只停留在 mock，未接真实 LS 和持久化恢复。

### 4.5 性能与资源消耗

`calls` 使用有界 deque、CLI 每图调用 `reset_figure`，内存风险已改善。但 `body_paras` 全量注入每图、`pair_records` 全量累积、无 SQL explain/N+1 检查仍是 16k 图规模下的隐患。

### 4.6 安全合规

对象存储已修复路径穿越，未发现硬编码密钥。仍缺少：LS/webhook 鉴权、字段级脱敏、Worker 配额限流、内容合规策略、真实权限控制。

## 5. 建议整改顺序

1. 修复 S9 不收敛判定传递：S9 在连续两轮无改善时直接置 `status=PENDING_REVIEW` 或路由读取 `no_improve`。
2. 让降级链真正走 S3/S5/S6/S8，并在置信度低于输出门槛时才转复核。
3. 将 `assign_scales` 接入 S6，完成比例尺三级归属、共享复制和旋转。
4. S8 遇到无映射 mask 时触发 E001/E002 类报警，禁止 `ASM_VALIDATED`。
5. 按 figure/图引用过滤 `body_paras`，保证描述文本作用域正确。
6. 移除 S7/S8 对 `ground` 的依赖，实现真实正文图版映射。
7. 将 claim 改为数据库原子认领，并补齐真实 ReviewBridge/webhook。
8. 修复 ruff/mypy，并补齐上述关键回归测试。

## 6. 未决问题

- 当前验收边界是否为“P0 mock 可运行”还是“V0.1 方案生产可实现”？建议在 README 或方案中明确。
- 降级场景是否允许直接产出低置信 Pair，还是必须全部转人工？当前代码选择后者，但方案降级矩阵倾向前者。
- 真实模型接入前，`svc.ground` 是否只应存在于测试夹具，而不应进入业务节点？

# DECISIONS — ADR / CR

> 只记正式决策，不记口头约定。编号永不复用；偏差必须带失效条件。

## ADR-001 v1 归档，books 保留

- 日期：2026-11-20
- 决策：除 `books/` 与 `.git/` 外，旧内容移入 `v1/`；`data/` 一并归档。
- 后果：旧实现只作参考；新根目录重建 `.gitignore` 与协同基线。

## ADR-002 协作档位 L0 + C

- 日期：2026-11-20
- 决策：Claude 编排 / Codex 实现 / dsh 验证，WIP=1。
- 失效条件：连续两波吞吐 ≤ 单 agent；人工介入 >3 次/日；冲突率 >20%。

## ADR-003 模型与端点

- 日期：2026-11-20
- 决策：codex/dsh 统一 `deepseek-v4.1-flash-1017`；codex 走 OpenAI 兼容 `/responses`，dsh 走 `openai-completions`。
- 失效条件：端点/模型下线；codex 移除 responses；dsh 配置格式变更。

## ADR-004 需求边界

- 日期：2026-11-20
- 决策：输入以 `books/<book>/data.xml + media` 为准；边界采用 2026-11-20 对齐建议默认
  （一器物一 Pair/单图、跨图不合并、无文本转复核、同 seq 共享图、L1 必须有尺、
  L2/L3 无尺标记、剥离序号、未映射复核、PNG+JSONL+ledger）。
- 产出：`specs/需求文档_V1.0.md` / `.docx`。
- 失效条件：人工评审修改边界；黄金集基线显示默认值不可行。

## ADR-005 映射形态与后缀规则

- 日期：2026-11-20
- 决策：
  - 第 4 项拆为 R-MAP-07a/b/c：N:1 合并；1:N 组合图共享、可分离视图需显式证据否则复核；N:N 位置对应。
  - 新增 R-ID-06：`M43:75a/b/c`、`M39:8-1/8-2` 默认是独立器物；仅正文明确同一件时才归并。
- 依据：真实图版 `image236.jpg`（串珠 N:1）、`image215.jpg`（釜+支架 1:N 组合）、`image250.jpg` + 正文"铁削 3件"（后缀独立）。
- 失效条件：领域复核认定后缀表示同一件器物的视图。

## ADR-006 比例尺规则

- 日期：2026-11-20
- 决策：采用 R-SCALE-01–05：前缀组硬绑；唯一尺共享；无前缀多尺 VL 兜底后复核；
  无图形尺 L1 复核、L2/L3 `no_scale`；成图复制并留痕。
- 依据：`image11.jpg`（单尺）、`image250.jpg`（三把前缀尺）、`image236.jpg`（范围前缀）、
  `image62.jpg`（单线图有尺）、`image777.jpg`（单版图无尺）。
- 失效条件：黄金集显示前缀组绑定不可行，或领域要求文字尺寸替代图形尺。

## ADR-007 需求 V1.0 冻结

- 日期：2026-11-20
- 决策：10 项补充决定全部采纳建议默认；`specs/需求文档_V1.0.md` 冻结为需求基线。
- 关键约束：多面板不裁切；跨图各自成 Pair + same_artifact_index；Pair 元数据与文本长度规则；
  通用 JSONL；内部训练使用；VLM P0 关闭；CPU/60s；JSONL 复核队列；OpenCV；本地文件存储。
- 后续：契约冻结 → 首批任务卡；需求变更走 CR/ADR。

## ADR-008 契约草案 V1.0

- 日期：2026-11-20
- 决策：落 `artifact_map.schema.json`、`pair_record.schema.json`、`alarms.md`、`naming.md`、
  `specs/crosswalk.md`；字段与需求 V1.0 对齐。
- 校验：JSON Schema metaschema + 样例实例通过。
- 状态：草案，待 `tests/contracts/` 与人工签字后冻结；实现者只读。

## ADR-009 契约冻结

- 日期：2026-11-20
- 决策：`contracts/` 标记 frozen；依据 T-001 契约测试 14 passed（commit 04c1109）
  与用户明确授权“Codex 实现、dsh 验证、Claude 编排及整体效果负责”。
- 变更：任何 schema/命名/报警码变更走 CR/ADR，实现者不得直接改。

## ADR-010 / CR-001 运行时 VLM

- 日期：2026-11-20
- 决策：运行时启用 `deepseek-v4.1-flash-1017` 作为 VLM，用于 OCR、整体视觉识别、效果判断/QC；
  PaddleOCR 并行/兜底；VLM 失败 fail-closed；结构化 JSON；密钥 `DASHSCOPE_API_KEY`。
- 影响：需求 §6.4 新增 R-VLM-01–05；后续 T-004 实现 VLM client + OCR 适配器。
- 失效条件：模型/端点下线；VLM 质量或成本不可接受；离线部署要求禁用 VLM。
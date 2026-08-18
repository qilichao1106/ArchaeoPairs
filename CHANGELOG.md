# Changelog

本项目遵循语义化版本（SemVer）。

## [0.4.0] - 2026-08-18

### Added（对齐《技术方案 V0.4》）
- 三线路图片分类架构：S2 输出 单器物线图/多器物线图/单器物彩图/多器物彩图/其它；单器物（线/彩）→ S7 单器物解析器 → S8 单器物组装器；多器物线图 → S3~S6 切分链路；多器物彩图与其它 → 归档丢弃。
- S7/S8 更名：彩板解析器 → 单器物解析器，匹配组装器 → 单器物组装器（弱化彩图表述）。
- B2：S2 单/多器物判定以 XML 器物号为一级证据（rule_b 序号歧义前置消解，parsers/keywords.py）。
- C1：S1 图注关联支持同图号分组 + 组内面积最大归属 + 图注前置回溯 + 相邻 figure-title 恢复（parsers/s1_xml.py）。
- 单器物路径命名 01 占位（naming.build_image_name）。
- 数据库迁移目录 migrations/V001__init.sql（Flyway/Liquibase 风格，§6.5.1）。
- 输入目录 examples → books；CLI 新增两种输入方式：run-book（单本）与 run-books（目录批量，自动遍历 books/<子目录>/data.xml），默认数据目录 books/。
- 预算对齐（§9.2/§5.1.4/T25）：移除 cost 单价配置（V0.4 无成本单价字段）；模型网关新增 Worker 配额限流（QPS 可配，vlm 12 / sam 16）与可配超时（VLM 30s / SAM 20s / OCR 10s），thresholds.example.yaml 新增 capability 段。

### Removed（V0.4 范围收敛）
- 移除成本帽/熔断：gateway.py 去 CostCapExceeded/熔断状态与成本累计；nodes.py 去 cost_cap 分支；Thresholds.per_figure_cap_cny 删除（保留 model_costs 单价）。
- 移除跨图合并：s8.merge_pair_records 及其测试、cli.py 汇总合并调用、PipelineFlags.cross_fig_merge 与 flags.example.yaml 对应项（V0.4 按单图独立输出）。

### Fixed
- 修复 routing.py route_single 与 parsers/keywords.py _artifact_signals 乱码 docstring。
- 代码头部注释版本引用 V0.3 → V0.4。

## [0.2.1] - 2026-08-17

### Added（新增《技术方案》图题器物号兜底识别，§2.2.5）
- 图题器物号兜底识别：figure-note 缺失或解析不出器物号时，从图题做器物号正则纯扫描（不做条目序号推断、重复出现去重）。21 书实测：无图注 figure 7,555 张（48.8%），其中图题含器物号 1,253 张（95.6% 为单号）。
- S3 输出 caption_artifacts 并参与正文预筛选；S5 仲裁：单一器物号判 rule_b（整图归属该器），多器物号判 seq_missing + E005（禁猜测）；图题兜底视为弱链①，置信=同链组合封顶×0.8 并标记 degraded。
- S10 降级判定将 caption_artifacts 视为可用映射证据，避免图题兜底图被误挂起。
- S7 彩板条目→artifact_id 兜底顺序调整为 图注 → 图题 → 链②。
- S1 ground、CLI 正文预筛选、§2.5 无器物号报告检测同步纳入图题信号。
- PairRecord.provenance 新增 art_source（figure_note/caption）溯源。
- 新增 tests/test_caption_fallback.py（19 例：纯扫描/S3/S5/S7/S10/合成 e2e + 洪洞南秦真实形态回归；洪洞南秦前 80 图实测产出 35 Pair）。

### Fixed
- COMPONENT_RE 部件号正则无法匹配 Zhb2/Zhb7 等多小写字母形态（§2.2.2/§2.2.4 反例清单要求），放宽为 `[A-Z][a-z]+\d+`。

## [0.2.0] - 2026-08-14

### Fixed（对应《代码评审_ArchaeoPairs_P0》缺陷清单）
- F1 链②正文筛选全角冒号失配：筛选前双侧归一化，Pair 描述文本覆盖率由 0.3% 提升至 78%（万州瓦子坪实测）。
- F2/F3 同号拆/区间拆过度配对：S5 配对改为位置对应（zip），禁笛卡尔积；全角"～"归一化，区间图注正确判 range_split。
- F4 圈号归一吞数字：artifact_id 按 1:1 span 回映原文（H83①:35 保留圈号），冒号统一归一。
- F6 figure↔figure-note 关联：同图号分组 + 图注前置回溯 + 多段合并 + 相邻图题恢复；违约清单带 fileref 与原因。
- F7 图题缺失：figure 保留进入管线（EXCLUDED 可见可统计），不再静默丢弃。
- F8 S7 彩板记录统一经 PairRecord（补齐 description_text 键）。
- F9 复核 event_id 确定性生成（figure_id+报警集合哈希），重跑不再重复建任务。
- F10 图版号正则补 O/〇 归一与拓片样式；图号后缀 O/o/0 归一为〇。
- F11 服务级降级落地：E400/E1000(OCR)→链③缺失降级；E1000(VLM/SAM)→PENDING_REVIEW；E102/E101→EXCLUDED。
- F12 S2 VLM 不可用关键词兜底（地层特例近似）。
- F13 parse_body 排除 figure-title/table-title/qr-caption 角色，防链②污染。
- F16 文件名去重注册表提升为 book 级共享（跨图防冲突）。

### Changed
- 彩板路径经 S9 必选终检（parse_plate → supervise → bridge_review）。
- CLI：报告级无器物号检测（§2.5）+ 正文段落按图预筛选（checkpoint 体量大幅下降）。
- CI：mypy 硬门禁、覆盖率门禁 fail_under=80。
- 文档/代码版本引用统一对齐《技术方案 V0.2》。

## [0.1.0] - 2026-08-11

### Added
- 从零搭建 src 布局包 `archaeopairs`，对齐《技术方案 V0.1》。
- LangGraph StateGraph 编排：S1–S10 十节点、诊断驱动条件边、SqliteSaver checkpointer、interrupt 人工复核。
- pydantic v2 数据契约（8 核心结构 + PairState）与 JSON Schema。
- 模型网关（录制/回放/限流/熔断/成本帽）、能力接口抽象 + mock 实现。
- SQLAlchemy 模型与 `ddl.sql`（幂等键复合索引、状态查询索引、JSONB GIN）。
- 三层测试（单元/契约/集成）+ examples 端到端（mock）。
- GitHub 规范文件：README/LICENSE/CONTRIBUTING/.gitignore/CI。

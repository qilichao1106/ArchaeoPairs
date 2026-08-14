# Changelog

本项目遵循语义化版本（SemVer）。

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

# Changelog

本项目遵循语义化版本（SemVer）。

## [0.1.0] - 2026-08-11

### Added
- 从零搭建 src 布局包 `archaeopairs`，对齐《技术方案 V0.1》。
- LangGraph StateGraph 编排：S1–S10 十节点、诊断驱动条件边、SqliteSaver checkpointer、interrupt 人工复核。
- pydantic v2 数据契约（8 核心结构 + PairState）与 JSON Schema。
- 模型网关（录制/回放/限流/熔断/成本帽）、能力接口抽象 + mock 实现。
- SQLAlchemy 模型与 `ddl.sql`（幂等键复合索引、状态查询索引、JSONB GIN）。
- 三层测试（单元/契约/集成）+ examples 端到端（mock）。
- GitHub 规范文件：README/LICENSE/CONTRIBUTING/.gitignore/CI。

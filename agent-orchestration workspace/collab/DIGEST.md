# DIGEST — 2026-11-20

## 完成

- v1 归档，`books/` 保留。
- codex / dsh 配置为 `deepseek-v4.1-flash-1017`，两端冒烟通过。
- 协作基线：AGENTS.md、CLAUDE.md、docs/协作开发方式.md、Plan.md、IMPLEMENT.md、collab/、docs/mh/。
- 需求 8 项边界 + 10 项补充决定全部确认，`specs/需求文档_V1.0.md` / `.docx` 已冻结。
- 契约草案：ArtifactMap / PairRecord JSON Schema、报警码、命名、crosswalk；schema 校验通过，待契约测试与签字。

## 阻塞

- 产品设计未冻结（M1 待人工评审）。

## 风险

- 新方案的数据/媒体根目录未定；`books/` 2GB 未入库。
- dsh 密钥依赖用户环境变量，当前终端需手动 export。

## 明日

- 人工审定 AGENTS.md 与协作方式。
- 评审 V1.0 设计草案或重新起草。
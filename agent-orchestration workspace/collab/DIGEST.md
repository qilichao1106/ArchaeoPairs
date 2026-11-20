# DIGEST — 2026-11-20

## 完成

- v1 归档，`books/` 保留。
- codex / dsh 配置为 `deepseek-v4.1-flash-1017`，两端冒烟通过。
- 协作基线：AGENTS.md、CLAUDE.md、docs/协作开发方式.md、Plan.md、IMPLEMENT.md、collab/、docs/mh/。
- 需求 8 项边界 + 10 项补充决定全部确认，`specs/需求文档_V1.0.md` / `.docx` 已冻结。
- 契约草案：ArtifactMap / PairRecord JSON Schema、报警码、命名、crosswalk；schema 校验通过。
- T-001 契约测试已合并：14 passed（commit `04c1109`）；dsh 沙箱 ACL 阻塞 pytest，由编排侧实跑并代提交。契约待人工签字。
- 契约已冻结（T-001 14 passed）；角色确认：Codex 实现 / dsh 验证 / Claude 编排与整体效果负责。
- T-002 已合并：XML 摄入 + FigureInput + 四线分类；dsh 独立 52 passed，全量 66 passed（`e2618b7` / `6d80d95`）。
- T-003 已合并：图注解析 + 文本映射 + 正文切分；dsh 独立 69 passed，全量 135 passed（`e23e67c` / `3c6eeee` / `f3738cb`）。
- CR-001：运行时启用 `deepseek-v4.1-flash-1017` VLM，用于 OCR/视觉识别/QC；T-004 已合并，59 passed；真实文本+图片冒烟通过（返回带 bbox 的 seqs JSON）。
- T-005 已合并：PaddleOCR 适配器 + Hybrid OCR；dsh 独立 47 passed，全量 241 passed（`187a788` / `100f6fc`）。
- T-006 已合并：OpenCV 分割 + View/RLE；dsh 独立 40 passed（发现并修复包含轮廓缺陷），全量 281 passed（`1aec426` / `a3293bc`）。
- T-007 已合并：序号绑定 + 视图归组 + ArtifactMap；dsh 独立 56 passed，全量 337 passed（`ca6907a` / `09cf21e`）；AC-02/AC-06 covered。
- T-008 已合并：比例尺三级绑定；dsh 独立 20 passed，全量 357 passed（`918fb3f` / `611c523`）；AC-03 covered。
- T-009 已合并：成图 + 命名；dsh 独立 65 passed，全量 422 passed（`603ee71` / `50af0dd`）；AC-05/AC-07 covered。

## 阻塞

- 产品设计未冻结（M1 待人工评审）。

## 风险

- 新方案的数据/媒体根目录未定；`books/` 2GB 未入库。
- dsh 密钥依赖用户环境变量，当前终端需手动 export。

## 明日

- 人工审定 AGENTS.md 与协作方式。
- 评审 V1.0 设计草案或重新起草。
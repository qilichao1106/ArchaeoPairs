# DIGEST — 2026-11-21

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
- T-010 已合并：单图管线 L1/L2/L3/L4；dsh 独立 19 passed，全量 441 passed（`3d7e232` / `a9e17eb` / `b23296d`）；AC-01/AC-04 covered。
- T-011 已合并：文件输出 + CLI + 真书冒烟；T-011 24 passed，全量 466 passed（`a6f72ef` / `8c94b87`）。
- T-011 真书加固（`c4e0639`）：字形网格读序号、标签 60px 最近绑定、比例尺框扩到尺线、辅助视图/大文本块/超大单元保护；`万州瓦子坪 --limit 10` 产出 **18 Pair / 18 PNG**，17 output + 1 `no_text` 复核；图九 8/8、图六 4/4、图四 6/6 全部单视图单器物，无 junk 图。
- T-012 已合并：dsh 独立新增 24 条加固冻结测试（`5082d7d`）；产品补丁 `d774464` 写入 `artifact_name`、清理目录行、整图 OCR 与字形网格并发；全量 **490 passed**。
- L1 轻量 OCR（`0a2ee70` / `9fb29b2` / `2ed477b`）：新增 scales-only 提示，序号只走字形网格；顶部图例带小字形独立过滤；比例尺漏检重试一次。`image9` 实跑 6 Pair / 6 PNG 且全部带比例尺。
- T-013 已合并：L1 轻量 OCR/图例带/比例尺重试冻结测试 12 passed（`eb313e3`）；可选 VLM 调用单次化 `c066a86`；全量 **502 passed**。
- 污染 Unit 防护（`4786795`）：含残留字形或重复尺线的 Unit 转 review 且不写成图（全量 502 passed）。
- 新增黄金集 `specs/golden_set.md`；新增批跑工具 `中间过程数据和脚本/batch_books.py`、产物审计 `audit_run.py`、批次汇总 `summarize_batch.py`、逐本审计 `audit_batch.py`、复核报告 `review_report.py`。

- 2026-11-21：整本《万州瓦子坪》415 图运行中；其余 15 本以 2 并发批跑中。

## 阻塞

- 产品设计未冻结（M1 待人工评审）。

## 风险

- 新方案的数据/媒体根目录未定；`books/` 2GB 未入库。
- dsh 密钥依赖用户环境变量，当前终端需手动 export。
- VLM 整图 bbox 不稳定，已改用“分割字形 + 网格识别”；遗留风险是图内图例行未被 OCR 识别时可能混入候选序号，超大单元保护会转复核。

## 明日

- T-012：黄金样例（逐图人工核对 Pair/命名/比例尺）+ 全书批跑。
- 全量 17 本批跑与失败清单；VLM QC 回环接入复核队列。
- AC-08 全量回归 + 负向对照取证。
# 需求 → AC → 测试 Crosswalk（V1.0）

> 需求基线：`需求文档_V1.0.md`（2026-11-20 冻结）。
> 测试建立后，把 `测试 nodeid` 与 `commit/artifact` 填满；任取一条 AC，一分钟内能定位。

## 需求分组 → AC

| 需求组 | 关键条款 | AC |
|---|---|---|
| 输入契约 R-IN-01–10 | books 布局、XML 角色、缺失处理、五分类路由 | AC-01 |
| 器物身份 R-ID-01–06 | 器物号归一、后缀保留、跨书隔离 | AC-02、AC-07 |
| 映射 R-MAP-01–08 | 四类基数、优先级、unbound、同号/多视图/跨图 | AC-02、AC-06 |
| 比例尺 R-SCALE-01–05 | 前缀组、共享尺、无前缀多尺、无尺分流 | AC-03 |
| 四条工作线 R-L1–L4 | L1 全链、L2/L3 直通、L4 归档 | AC-01、AC-04 |
| 输出 R-OUT-01–08、R-IMG-01–10、R-NAME-01–06 | PairRecord、成图、命名、跨图索引 | AC-04、AC-05、AC-07 |
| 质量 R-QC-01–08 | 自动/复核分流、VLM 边界、复核队列 | AC-06、AC-08 |
| 运行 R-OPS-01–08 | 批处理、幂等、离线、许可 | AC-08 |
| 数据 R-DATA-01–04 | PNG+JSONL+ledger、阶段产物、可复现 | AC-04、AC-08 |

## AC 台账

| AC | 内容 | 测试 nodeid | 证据 | 状态 |
|---|---|---|---|---|
| AC-01 | 四条工作线路由，L4 零 Pair | `tests/qa/T-002/`, `tests/qa/T-010/` | T-002/T-010 | covered |
| AC-02 | 1:1 / N:1 / 1:N / N:M 映射正确 | `tests/qa/T-003/`, `tests/qa/T-007/` | T-003/T-007 | covered |
| AC-03 | 比例尺三级绑定与来源落盘 | `tests/qa/T-008/` | T-008 | covered |
| AC-04 | L2/L3 整图直通、01 命名 | `tests/qa/T-010/` | T-010 | covered |
| AC-05 | 成图白底/纯平移/留白/比例尺置底 | `tests/qa/T-009/` | T-009 | covered |
| AC-06 | 未映射/缺视图进入 unbound 并复核 | `tests/qa/T-007/` | T-007 | covered |
| AC-07 | 命名规则（图号、冒号、_N、后缀） | `tests/qa/T-009/` | T-009 | covered |
| AC-08 | 全量回归 + 负向对照 | 待建 | 待建 | gap |
| AC-09 | 分割掩膜/视图质量（R-L1-01 派生） | `tests/qa/T-006/` | T-006 | covered |

状态枚举：`covered` / `partial` / `failed` / `gap` / `out_of_scope`。只有测试进主干且通过才可标 `covered`。

## T-001 契约测试说明

- T-001（commit `04c1109`）只验证 **JSON Schema 形状**：14 passed。
- 不证明 AC-02 的映射行为，也不证明 AC-07 的命名输出；二者当时为 `gap`，后由 T-007（AC-02）/T-009（AC-07）覆盖。
- 证据：`selfcheck/T-001/pytest.log`；copy-proof 指向 `worktrees/dsh/T-001`。

## T-002 验收说明

- 实现 `e2618b7`（codex）；测试 `6d80d95`（dsh）。
- dsh 独立执行：52 passed；负向对照（图题优先注入）→ 1 failed，恢复 → 52 passed；全量回归 66 passed。
- AC-01 当时标 `partial`：五分类→四线映射已覆盖；流水线实际路由与 L4 零 Pair 后由 T-010 覆盖。
- 证据：`tests/qa/T-002/`；copy-proof 指向 `worktrees/dsh/T-002`。

## T-003 验收说明

- 实现 `e23e67c` + `3c6eeee`（codex/编排侧例外修复）；测试 `f3738cb`（dsh）。
- dsh 独立执行：69 passed；负向对照（区间 bug 注入）→ 2 failed，恢复 → 69 passed；全量回归 135 passed。
- AC-02 标 `partial`：文本层四类基数与冲突已覆盖；视图/比例尺映射待后续卡。
- 证据：`tests/qa/T-003/`；copy-proof 指向 `worktrees/dsh/T-003`。

## T-004 验收说明

- 实现 `cb82f45`（codex）；测试 `0ede96d`（dsh）。
- dsh 独立执行：59 passed；负向对照（不重试 429/5xx）→ 5 failed，恢复 → 59 passed；全量回归 194 passed。
- 真实 VLM 冒烟：文本返回 OK；`image11.jpg` 图片 OCR 返回带 bbox 的 seqs JSON（usage/latency 可观测）。
- AC-03 标 `partial`：VLM OCR/比例尺读取能力已覆盖；三级绑定与视图匹配待后续卡。

## T-005 验收说明

- 实现 `187a788`（codex）；测试 `100f6fc`（dsh）。
- dsh 独立执行：47 passed；负向对照（Hybrid 降级反转）→ 4 failed，恢复 → 47 passed；全量回归 241 passed。
- 覆盖 Paddle 3.x/legacy、flat/quad bbox、seq/scale/text 分类、Hybrid 单边降级与双边失败。
- 证据：`tests/qa/T-005/`；copy-proof 指向 `worktrees/dsh/T-005`。

## T-006 验收说明

- 实现 `1aec426`（codex）；测试 `a3293bc`（dsh）。
- dsh 独立执行：40 passed；验证中发现包含轮廓剔除缺陷（1 failed），修复后 40 passed；全量 281 passed。
- 覆盖 IO、分割/阅读序、孔洞/包含剔除、mask/bbox、RLE、负向输入。
- AC-09 `covered`；卡面原写 AC-01 属标签复用，实际验收以 AC-09 为准。

## T-007 验收说明

- 实现 `ca6907a`（codex）；测试 `09cf21e`（dsh）。
- dsh 独立执行：56 passed；负向对照（status 恒 composed）→ 6 failed，恢复 → 56 passed；全量 337 passed。
- AC-02、AC-06 标 `covered`：文本/视图四类基数、unbound/冲突、复核状态均已覆盖。
- 证据：`tests/qa/T-007/`；copy-proof 指向 `worktrees/dsh/T-007`。

## T-008 验收说明

- 实现 `918fb3f`（codex）；测试 `853867e`（dsh）；测试重名修复 `611c523`。
- dsh 独立执行：20 passed；负向对照（去掉 E004）→ 3 failed，恢复 → 20 passed；全量 357 passed。
- AC-03 `covered`：L1/L2/L3、共享、来源落盘、Unit 应用与无尺复核均已覆盖。
- 证据：`tests/qa/T-008/`；copy-proof 指向 `worktrees/dsh/T-008`。

## T-009 验收说明

- 实现 `603ee71`（codex）；测试 `50af0dd`（dsh）。
- dsh 独立执行：65 passed；负向对照（margin=0）→ 10 failed，恢复 → 65 passed；全量 422 passed。
- AC-05、AC-07 标 `covered`：白底/纯平移/margin/比例尺行、图号/冒号/01/_N/后缀均覆盖。
- 证据：`tests/qa/T-009/`；copy-proof 指向 `worktrees/dsh/T-009`。

## T-010 验收说明

- 实现 `3d7e232` + 编排侧修复 `a9e17eb`；测试 `d420774`（重命名修复 `b23296d`）。
- dsh 独立执行：19 passed；负向对照（辅助视图过滤失效）→ 6 failed，恢复 → 19 passed；全量 441 passed。
- AC-01、AC-04 标 `covered`：四线路由、L4 零 Pair、L2/L3 整图与 01 命名均覆盖。
- 证据：`tests/qa/T-010/`；copy-proof 指向 `worktrees/dsh/T-010`。
## T-011 验收说明

- 实现 `a6f72ef`（codex）；测试 `8c94b87`（dsh），T-011 24 passed。
- 全量回归：**466 passed**。
- 真书冒烟：`books/万州瓦子坪 --limit 10`；10 图 → 18 Pair / 18 PNG；17 output + 1 `no_text` 复核（`2004CWWM11:6`）；L2/L3 直通 2 图、L4 归档 7 图。
- 合并后加固 `c4e0639`：字形网格读序号、60px 最近标签绑定、比例尺框扩到尺线、大文本块/超大单元保护；复跑同一冒烟仍为 18/18，图九 8/8、图六 4/4、图四 6/6，无 junk 图。
- AC-04/AC-05/AC-07 保持 `covered`；AC-08 仍未覆盖（全量 17 本批跑 + 负向对照未做）。
- 证据：`runs/smoke_final/pairs.jsonl`、`ledger.jsonl`、`pairs/*.png`。

## T-012 加固冻结测试说明

- 测试：dsh 独立会话 `5082d7d`（24 passed）；产品补丁 `d774464`。
- 覆盖 `c4e0639`/`d774464` 的字形网格序号、重复序号清洗、文本块不吞绘图、比例尺扩到尺线、超大单元复核、L1/L2/L3 `artifact_name`。
- 全量回归：**490 passed**；selfcheck OK。
- AC-02/AC-05/AC-06 的边界行为不变，仍为 `covered`。

## T-013 轻量 OCR 冻结说明

- 测试 `eb313e3`（12 passed），实现 `c066a86`；覆盖 scales-only 优先/回退、缺尺重试一次、字形为空回退整图、顶部图例带过滤。
- 全量回归 **502 passed**。

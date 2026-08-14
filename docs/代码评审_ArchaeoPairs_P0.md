# ArchaeoPairs 代码评审报告（P0 实现）

- **评审对象**：仓库 `ArchaeoPairs` 的 `src/archaeopairs`（S1–S10 智能体 + LangGraph 编排 + 网关/存储/能力接口）与 `tests/`、CI、配置
- **评审依据**：《技术方案 V0.1/V0.2》及《评审意见_多智能体方案_V0.2.md》（本仓库 docs/）；examples 21 份报告全量数据
- **评审方式**：全量通读源码（38 个源文件）与 16 个测试文件；运行 pytest/ruff/mypy/coverage；在真实报告（万州瓦子坪 413 图全量、郑州商城 2299 图全量）上用 mock 能力接口实跑管线并分析产出
- **结论先行**：工程骨架质量好（分层清晰、契约注入、85% 行覆盖、静态检查全绿、74 测试通过），但**在真实数据上存在 4 个 P0 级功能缺陷与 1 个系统级错配**，且测试体系因夹具全 ASCII 而系统性漏检真实数据形态。评审意见中的 P0-1/P0-2/P0-3 与 P1-5 等缺陷已在代码与实测中逐一复现。

---

## 一、实测基准（真实数据实跑结果）

### 1.1 万州瓦子坪（413 图全量，mock 能力）

| 指标 | 数值 | 备注 |
|---|---|---|
| 进入管线 figure | 121/413（29%） | 其余 292 图因 caption 缺失被 E102 违约**直接丢弃** |
| violations | 292 | 且 id 不唯一（fig_84 重复 3 次）、不含 fileref，无法定位返工 |
| 状态分布 | OUTPUT 75 / PENDING_REVIEW 40 / CLASSIFIED 6 | 复核率 33%（mock 分类失真所致，见 §2.6） |
| Pair 产出 | 368 条 | **367 条 description_text 为 null**（99.7%），25 条记录缺 description_text 键 |
| 过度配对 | 图九、图四各多出 2 条 | "4、6. 陶魁（…：5、…：10）" 产出 4 条（应 2 条） |

### 1.2 郑州商城（2299 图全量，mock 能力，耗时 398.6s）

| 指标 | 数值 | 备注 |
|---|---|---|
| 进入管线 figure | 808/2299（35%） | 1491 图（64.9%）因 caption 缺失被违约丢弃 |
| 状态分布 | OUTPUT 305 / PENDING_REVIEW 292 / CLASSIFIED 211 | 复核率 36%，mock 分类失真放大（见 §2.6） |
| Pair 产出 | 5590 条（均 6.9 条/图，含过度配对与图版） | 其中 4275 条（76.5%）description_text 为空 |
| 单图平均耗时 | ≈0.49s（纯 mock 无真实模型） | body_paras 全量注入 State 的开销证据（§三.1） |

### 1.3 关键反例（对应技术评审 P0-1/P0-3）

- `万州瓦子坪:image9`（图四器物组合图本体）→ **PENDING_REVIEW**；`万州瓦子坪:image10`（93×27 比例尺条图）→ **OUTPUT** 并产出 4 条 Pair。真实组合图进复核、比例尺条图被当作器物图配对——"figure↔figure-note 紧邻关联"缺陷的实证后果。

---

## 二、功能正确性缺陷（按严重级）

### P0 级

#### F1 链②正文匹配失效：全角冒号导致全部 Pair 描述文本为空（实锤）

- **位置**：`src/archaeopairs/agents/s3.py:20-21`
- **机理**：图注解析出的 artifact_id 已经归一化为半角冒号（`2004CWWM11:5`），正文 XML 中却是全角冒号（`2004CWWM11：5`），而筛选条件是 `any(a in p.get("text","") for a in note_arts)` —— 未对正文做归一化即做子串匹配。
- **复现**：`'2004CWWM11:5' in '鼎 1件。2004CWWM11：5，子母口……'` → `False`。
- **后果**：瓦子坪 368 条 Pair 中 367 条无描述文本；链②（正文）在绝大多数报告上实际失效，Pair 三元组退化为二元组。
- **修复**：筛选前对正文文本调用 `s3_note.normalize()`；或改为先切分再按 artifact_id 归一化索引。同时补一条全角冒号契约测试。

#### F2 同号拆/区间拆过度配对（seq×artifact 笛卡尔积）

- **位置**：`src/archaeopairs/agents/s5.py:45-49`（split_same_seq 分支）
- **机理**：`"4、6. 陶魁（2001CWWM6：5、2001CWWM6：10）"` 解析为 seq_list=[4,6]、arts=[5,10]，split_same_seq 分支把**两个 artifact 全部挂到两个 seq**（extend），产出 4 条 Pair；正确语义是按位置 zip（4→:5，6→:10，共 2 条）。
- **实证**：瓦子坪实跑产出 `图九_4_2001CWWM6-5.png / 图九_4_2001CWWM6-10.png / 图九_6_2001CWWM6-5.png / 图九_6_2001CWWM6-10.png` 4 条；图四同理多 2 条。
- **修复**：split_same_seq 与 range_split 统一为位置对应（zip）；仅当 seq 数 < artifact 数时把余量按方案语义处理（转 PENDING_REVIEW 或按声明拆分），禁止笛卡尔展开。

#### F3 全角区间号"～"未被归一化，区间图注误判为同号拆

- **位置**：`src/archaeopairs/agents/s5.py:20`（`("~" in it["seq"])` 只查半角）
- **机理**：`s3_note.normalize()` 只归一冒号与圈号；图注"1～4. 豆（M3:4、M3:2、M3:3、M3:1）"的 seq 原文仍是"1～4"，`has_range` 为 False → case_type=split_same_seq → 与 F2 叠加产生 16 条错误 Pair（应 4 条）。
- **复现**：`s5._case([{'seq':'1～4',...}])` → `split_same_seq`；半角"1~4" → `range_split`。
- **修复**：normalize() 增加 ～→~（含全角波浪线）；has_range 判定使用归一化后的 seq。

#### F4 圈号归一吞并数字，器物号键被改写

- **位置**：`src/archaeopairs/parsers/s3_note.py:17-21`
- **机理**：`①→1` 直接替换使 `H83①:35 → H831:35`、`C11T112③:27 → C11T1123:27`——与方案 §2.2.2 单测反例"匹配 H83①:35（圈号作为前缀字符保留）"矛盾，器物号键（book_id:artifact_id 唯一键与文件名）被永久改写，栎阳城/郑州商城类层位号全部受影响。
- **修复**：圈号归一仅用于匹配（生成归一化副本），artifact_id 原文保留；或归一为带分隔符形式（`H83{1}`）并同步文件命名规则。

#### F5 服务级降级路径未实现，E400/E1000/E500 全部被打成 PENDING_REVIEW

- **位置**：`src/archaeopairs/orchestration/nodes.py:17-29`
- **机理**：`_guard` 将一切 `ArchaeoPairsError` 映射为 PENDING_REVIEW；方案 §3.7/§6.2.1 要求 OCR 全失败（E400）→ 链③缺失降级、三链冲突（E500）→ Supervisor 仲裁、服务不可用（E1000）→ DEGRADED 状态。代码中 FigureStatus.DEGRADED **无任何节点写入**，状态机支路是死状态。
- **后果**：OCR 服务抖动时全批次灌入人工复核队列；熔断触发后所有排队图直接 PENDING_REVIEW 而非挂起续跑。
- **修复**：`_guard` 按错误码分派：retryable/服务类错误 → DEGRADED 挂起；E400 → 置链③缺失标记走降级矩阵；E500 → 触发 S9 仲裁。

### P1 级

#### F6 figure↔figure-note 关联规则与真实形态冲突（技术评审 P0-1 的代码级实证）

- **位置**：`src/archaeopairs/parsers/s1_xml.py:52-58`
- 问题：仅取"其后紧邻的第一个 figure-note para"——图注前置（瓦子坪 L5005）、一图多段注（L128-129）、同图号多 figure（图四×2）、条图夹断（image10）四类反例全部错配。§1.2 实证已给出后果。
- **修复**：双向回溯 + 同图号 figure 集合归属 + 多段合并；图注内序号集合连续性校验，失败入违约清单。

#### F7 图题缺失的违约粒度：71% 图被静默丢弃（技术评审 P0-2 的实证）

- **位置**：`src/archaeopairs/parsers/s1_xml.py:43-48`（`cap is None → violation + continue`）
- 瓦子坪 292/413、郑州商城约 65% 的 figure 被直接丢弃（不进入管线、不生成命名回退）。方案口径是"违约转清单+排除"，但当前中间态数据下该口径造成大规模数据损失，且 violations 只记录 `fig_N` 假 id，无法回链原文。
- 另外 `para role="figure-title"` 游离形态（大兴东庄营 51 处、瓦子坪 12 处章节级）完全不支持。
- **修复**：violations 记录 fileref+所在行；对 caption 缺失图提供"命名回退 + 继续处理"开关（或明确列入上游返工口径）；支持 figure-title 的三种容器形态。

#### F8 S7 彩板记录字段与 PairRecord schema 不一致

- **位置**：`src/archaeopairs/agents/s7.py:30-37`
- S7 构造的 pair_records 无 `description_text`/`quality_flags` 键（实测 25 条记录缺键），与 S8 产出的 PairRecord 字段集合不一致，下游消费方需 `r.get()` 兜底。
- **修复**：S7 统一经 `PairRecord(...).model_dump()` 产出。

#### F9 复核事件幂等键不幂等

- **位置**：`src/archaeopairs/agents/s10.py:30`、`integrations/label_studio.py:23-25`
- `event_id = figure_id + uuid4()`：同一 figure 重跑/续跑生成新 event_id → 重复建复核任务；MockReviewBridge.create_task 还会**覆盖**同 figure 旧任务。与方案"event_id 幂等去重"直接冲突。
- **修复**：event_id 由 (figure_id, 报警码集合) 确定性哈希生成；bridge 对 OPEN 任务去重。

#### F10 S7 图版号/图号归一化缺口（技术评审 P1-5 的代码级确认）

- **位置**：`src/archaeopairs/agents/s7.py:13`、`naming.py:10`
- `_PLATE_NO_RE` 不匹配"图版三O"（O 不在字符集）；`_FIG_RE` 恰好把"图二六O"的 O 当后缀吃掉（偶然正确）；"拓片三七"式拓片图版完全不匹配；白帝城粘连标题（一段两标题）未检测。
- **修复**：字符集补 O/〇/0 归一；拓片标题正则；S1 增加图版标题粘连检测。

#### F11 S2 无 VLM 降级路径、无地层特例强制 type A

- **位置**：`src/archaeopairs/agents/s2.py`
- 方案 §3.7：VLM 不可用 → 图题关键词规则兜底（含地层特例）；代码只有一条 `gateway.call("vlm", ...)` 通路，VLM 抖动即整图失败（经 _guard 转 PENDING_REVIEW）。ground 侧（`s1_xml.py:72-77`）用"caption 关键词 + 有无图注条目"近似实现了 mock 分类，但真实 VLM 通路没有兜底。
- **修复**：S2 增加 try/except 关键词兜底分支；地层关键词 + 器物轮廓的强制 type A 规则。

#### F12 拓片类、条状比例尺图、表格均无处理（技术评审 P1-2/P1-3/P0-3 确认未落地）

- S2 决策无拓片/比例尺条类别；比例尺三级只处理图内比例尺，跨 imagedata 比例尺条图（实测 155 个）会被判 discarded 或误配对（§1.2 实证 image10）；`s1_xml.parse_body` 未排除表格 `html-content` 属性与 `caption role="table-title"` 文本，514 张表的内容会污染链②正文。

### P2 级（要点）

- **F13** `s1_xml.parse_body` 把 caption 内 `para role="figure-title"` 混入正文（图题污染链②语料）。
- **F14** 无器物号报告检测未按方案 §2.5 实现（无报告级三信号检测，仅 per-figure 单信号，且每个 figure 都拼全文）。
- **F15** S6 中"mask 未获任何比例尺而全图比例尺均已有序号归属"时 scale_level=3 静默通过，无报警（方案三级规则未覆盖该组合，需补齐）。
- **F16** dedup registry 每图重置（`s8.py:24`）：跨图同图号同器物会生成同名文件互相覆盖（本地 store 的 put 无锁、无冲突检测）。
- **F17** `nodes._guard` 把通用 `HardConstraintError` 一律映射为 E007，丢失原始违规类型。
- **F18** S7 走 `parse_plate → bridge_review` 直连，未经 S9 终检（与 V0.2"S9 必选终检"及 §4.7.3"S7 共享 S8/S9 质检"冲突；代码选择了附录 B 拓扑，文档需统一）。
- **F19** pyproject/README/ddl.sql/db.py 头注释仍写"对齐 V0.1"，与 V0.2 修订（candidate_images、S9 终检、幂等键分层等已在代码落地）脱节；CHANGELOG 未记录 V0.2 整改。

---

## 三、性能与资源

1. **body_paras 全量注入每个 figure 的 State（P1）**：`cli.py:63` 把整本书的正文段落塞进每个 figure 的初始 State，经 SqliteSaver 全量序列化入 checkpoint。郑州商城约 1.5 万段落 × 2299 图 → checkpoint 膨胀、invoke 序列化开销 O(图数×书文本量)；S1 `_has_artifact_signal` 每图拼接全文再正则。应改为 book 级只读缓存（图内仅存 para 索引/指针），或 S3 按图号先裁剪再入 State。
2. **SQLite 单文件 + 多 Worker 并发写**（方案 P2-1 未解决）：P0 单机顺序跑可接受，但要为 §9.3 并发调度预留 WAL/分库。
3. `parse_report` 通过修改 `el.tag` 剥离命名空间，对 16k 图规模可用，但重复 `root.iter()` 多次全树遍历（figure 映射、parse_body 各一遍），可合并单遍扫描。

---

## 四、工程质量（多维度）

### 4.1 优点（应保持）

- **分层与注入**：能力接口（VLM/SAM/OCR Protocol）→ 网关 → 智能体 → 编排节点，依赖方向干净；Services 容器注入，节点纯函数化，可测性强。
- **硬约束落地**：掩膜禁 bbox（S6 抛 HardConstraintError）、比例尺三级（assign_scales+E004）、报警即停禁输出（_guard/路由/测试全覆盖）、Feature Flag 与硬约束分离——追溯矩阵 18 条中多数有代码落点。
- **V0.2 修订已在代码中**：FusedMapping seq→多 artifact、PairRecord.candidate_images/image_merge_mode、S9 必选终检+no_improve、幂等键不含 iteration、s3_llm_confirm 默认开。
- **工程质量基座**：pytest 74 通过；ruff/mypy 全绿；行覆盖 85%（s1_xml/s3_text/schemas 100%）；Gateway 重试/熔断/成本帽/回放语义正确且有测试；对象存储路径穿越防护 + tmp/rename 原子写；pydantic v2 约束（ge/le）到位。
- **测试设计**：路由表逐分支、硬约束逐条、网关故障注入（flaky/circuit/cost）——三层测试思路清晰。

### 4.2 问题

1. **测试夹具与真实数据形态脱节（P0，测试维度）**：所有 fixture 使用 ASCII 冒号/半角~；无一条全角"："、"～"、圈号"①"、图版粘连、同图号多图、条状比例尺图的用例。三个 P0 级缺陷（F1/F2/F3）全部处于被覆盖行内（s3_text 100%、s5 高覆盖）却全部漏检——"覆盖率"掩盖了"形态覆盖"为零。**建议**：从 examples 抽取真实样本（至少覆盖 §5.6 全部语法用例 + 评审 P0-1/P0-2/P0-3 的反例）作为契约测试 fixture。
2. **CI 门禁形同虚设（P1）**：`mypy src || true` 失败不阻断；coverage `fail_under = 0` 无门槛；`examples/*` 在 .gitignore 中 → GitHub CI 上 e2e 测试全部 skip（实测 `git ls-files examples` = 0）。方案 §10.4"golden set 进 CI 回归门禁、指标下降 >5% 阻断"完全未落地。**建议**：mypy 硬门禁；coverage 设 ≥80%（确定性模块）门槛；examples 以校验和清单/内部制品方式纳入数据回归（golden 子集进库）。
3. **文档-代码-版本三方漂移**：F19 + `Settings` 声明"环境变量注入"但未继承 BaseSettings、`claim_figure` 无 SKIP LOCKED、`ReviewTaskRow` 缺 ddl.sql 中的 created_at/updated_at、SQLAlchemy 模型无外键（ddl 有 ON DELETE CASCADE）——需一次对齐。
4. **无真实 VLM/SAM/OCR 实现与选型实验**：能力接口只留 Protocol + mock，符合"P0 后冻结"口径，但方案 P1（内容合规验证）/P2（第一周基准数据）在代码层**没有预留任何合规拦截钩子与评测脚本入口**（无审核网关适配点、无 golden set 评估代码）。建议 P0 收尾前补 `eval/` 骨架。

---

## 五、安全与合规

- ✅ 路径穿越防护（`object_store._safe`）、原子写、真实配置不入库（*.example.yaml + .gitignore）、SQL 注入面小（SQLAlchemy 参数化）。
- ⚠️ **未实现**：模型网关鉴权与每 Worker 配额（方案 §8.4"防 GPU 被打爆"）；S3 LLM 确认的正文输入截断与指令隔离（方案 §8.4，代码直接全文传参）；内容审核拦截（方案 P1 最高优先级否决项）在代码中无任何适配点；复核导出审批/SSO 未涉及（P0 可后置，但需在 README 声明边界）。
- ⚠️ 本地 store 无并发锁；网关 `calls` 录制含请求/响应全量，无脱敏/加密（录制回放文件需明确访问控制）。

---

## 六、对照《技术评审意见》的落地矩阵

| 评审意见 | 代码状态 | 备注 |
|---|---|---|
| P0-1 figure-note 关联规则 | ❌ 未解决 | §2 F6，实证 image9/image10 错配 |
| P0-2 图题契约/回退命名 | ⚠️ 部分 | S8 有 fallback，但 parser 层 71% 图被丢弃（F7） |
| P0-3 独立比例尺条图 | ❌ 未实现 | §2 F12 |
| P0-4 禁坐标距离适用范围 | ❌ 未澄清 | 代码无标注↔mask 绑定规则定义（P0 阶段可后置，需文档先行） |
| P1-1 彩板 XML 直读 | ✅ 部分 | S7 已优先用 figure-note（好于方案）；缺正文图版引用校验链、一版多 figure 聚合 |
| P1-2 拓片类 | ❌ 未实现 | F12 |
| P1-3 表格排除声明 | ❌ 未实现 | F12（含 html-content 污染） |
| P1-4 图注异常形态 | ❌ 未实现 | 描述段/极简图注无识别 |
| P1-5 图号 O/〇 归一化 | ⚠️ 部分 | _FIG_RE 偶然吞 O 为后缀；图版正则缺 O/拓片（F10） |
| P1-6 P0 选书 | ⚠️ 部分 | e2e 测试选郑州商城/白帝城；按实测应加瓦子坪 |
| P1-7 像素元素白名单 | ❌ 未落地 | 文档层面 |
| P1-8 合规验证交付物 | ❌ 无代码支撑 | 见 §五 |
| P2-1 SQLite 并发 | ❌ 未解决 | §三.2 |
| P2-2 版本退休/GC | ❌ 未解决 | 无旧状态清理 |
| P2-3 成本模型 | ⚠️ 部分 | model_costs 有单价字段，缺全量测算表 |
| P2-4 文本跨章节合并 | ❌ 未解决 | description_text 单值 |
| P2-5 拓扑一致性 | ⚠️ 部分 | 代码选 mermaid 拓扑（S7→S10），§4.7.3 文字待改 |
| P2-6 状态机命名 | ✅ 已统一 | VALIDATED/ASM_VALIDATED 一致 |
| P2-7 S9 预算表述 | — | 文档问题，与代码无关 |
| P2-8 E007 占位 | ✅ 已定义 | errors.py E007 类存在，仍无触发点（保留占位） |
| P2-9 术语 | — | 文档问题 |
| P2-10 golden 分层补形态 | ❌ 未落地 | 无 golden set 资产与评估代码 |
| P2-11 条图旋转联动 | ❌ 未实现 | 依赖 P0-3 |

---

## 七、修复行动项（按优先级）

| # | 行动 | 位置 | 级别 |
|---|---|---|---|
| 1 | 正文筛选先 normalize 再匹配；补全角冒号契约测试 | s3.py:20 | P0 |
| 2 | split_same_seq/range_split 改位置对应（zip），禁笛卡尔 | s5.py:45-55 | P0 |
| 3 | normalize() 增 ～→~ 与圈号"归一副本+原文保留" | s3_note.py | P0 |
| 4 | figure-note 双向回溯关联 + 多段合并 + 违约清单带 fileref | s1_xml.py | P0 |
| 5 | E400/E500/E1000 分级处置 + DEGRADED 状态落地 | nodes.py/s5 | P0 |
| 6 | caption 缺失回退命名/继续处理开关；violations 可定位 | s1_xml.py/cli | P1 |
| 7 | S7 统一 PairRecord 产出；图版正则补 O/拓片；event_id 确定性 | s7/s10 | P1 |
| 8 | body_paras 出 State（book 级缓存）；S2 VLM 降级兜底 | cli/s3/s2 | P1 |
| 9 | CI 硬门禁（mypy/cov ≥80）+ 真实形态契约测试 + golden 子集入库 | CI/tests | P1 |
| 10 | 文档-代码对齐（V0.2 引用、ddl/db 漂移、CHANGELOG） | 仓库级 | P2 |

---

## 八、总结

代码实现"忠实于方案骨架、偏离于真实数据"：编排、网关、硬约束、存储、错误体系等工程件完成度高且可测；但 S1/S3/S5 三个"确定性"环节在真实数据形态上全部存在缺陷（关联错配、冒号失配、过度配对），直接导致"真实组合图进复核、比例尺条图被配对、99.7% 的 Pair 无描述文本"的系统性质量事故。**P0 收尾前必须完成 §七 1–5 项修复，并用 examples 真实形态契约测试锁死**；否则 mock 链路跑得再绿，接入真实 VLM/SAM 后上述缺陷会被放大而非收敛。

---

## 九、修复状态（2026-08-14 已完成）

### 9.1 修复后实测对比（mock 能力接口，全量实跑）

| 指标 | 万州瓦子坪 修复前 | 修复后 | 郑州商城 修复前 | 修复后 |
|---|---|---|---|---|
| 进入管线 figure | 121/413（292 静默丢弃） | 413 全量（280 EXCLUDED 可见可定位） | 808/2299（1491 丢弃） | 2299 全量（1475 EXCLUDED 可见） |
| Pair 总数 | 368 | 290 | 5590 | 2161（消除笛卡尔膨胀） |
| description_text 非空 | 1（0.3%） | 227（78%） | 1315（23.5%） | 1365（63.2%） |
| 缺 description_text 键 | 25 | 0 | — | 0 |
| image9 组合图 / image10 条图 | REVIEW / OUTPUT（错配） | **OUTPUT / REVIEW（纠正）** | — | — |
| 陶魁（4、6. :5、:10） | 4 条（应 2） | **2 条（位置对应）** | — | — |
| 全量耗时 | — | 19.7s | 398.6s | 248.2s（-38%） |

### 9.2 缺陷修复清单

| 编号 | 状态 | 位置 |
|---|---|---|
| F1 全角冒号失配 | ✅ 双侧归一化筛选 + 契约测试 | agents/s3.py、tests/test_real_shape_regressions.py |
| F2 同号拆笛卡尔 | ✅ 位置对应 zip + 数量不一致转冲突 | agents/s5.py |
| F3 全角～区间误判 | ✅ normalize 增 ～/〜→~ | parsers/s3_note.py |
| F4 圈号吞数字 | ✅ 1:1 span 回映原文（H83①:35 保留）、冒号统一 | parsers/s3_note.py、s3_text.py |
| F5 服务降级缺失 | ✅ E400/E1000(OCR)→降级、E1000(VLM/SAM)→REVIEW、E102/E101→EXCLUDED | orchestration/nodes.py、errors.py、gateway.py |
| F6 图注关联缺陷 | ✅ 同图号分组+前置回溯+多段合并+相邻图题恢复 | parsers/s1_xml.py |
| F7 图题缺失静默丢弃 | ✅ figure 保留（EXCLUDED 可见）、violations 带 fileref | parsers/s1_xml.py |
| F8 S7 Schema 不一致 | ✅ 统一 PairRecord | agents/s7.py |
| F9 event_id 不幂等 | ✅ 确定性哈希 + bridge 去重 | agents/s10.py、integrations/label_studio.py |
| F10 图版/图号 O 归一 | ✅ 图版正则补 O/拓片、图号 O/o/0→〇 | agents/s7.py、naming.py |
| F11 S2 无降级兜底 | ✅ 关键词兜底（地层特例近似） | agents/s2.py、parsers/keywords.py |
| F12 拓片/条图/表格 | ⚠️ 拓片与条图分类待真实 VLM 接入；表格污染已防（parse_body 角色过滤） | parsers/s1_xml.py |
| F13 图题混入正文 | ✅ 角色过滤 | parsers/s1_xml.py |
| F14 无器物号报告检测 | ✅ 报告级检测（§2.5） | cli.py、agents/s1.py |
| F16 文件名跨图冲突 | ✅ book 级共享注册表 | agents/__init__.py、s8.py |
| body_paras 入 State | ✅ 按图预筛选（耗时 -38%、checkpoint 体量大幅下降） | cli.py、agents/s3.py |
| 彩板经 S9 终检 | ✅ parse_plate→supervise→bridge_review | graph.py、routing.py |
| CI 门禁 | ✅ mypy 硬门禁 + 覆盖率 fail_under=80 | ci.yml、pyproject.toml |
| 文档版本对齐 | ✅ V0.1→V0.2（src/docstring/pyproject/README/ddl）+ CHANGELOG 0.2.0 | 仓库级 |

### 9.3 遗留事项（下一轮）

- F12 拓片图类与条状比例尺图的 S2 视觉判定（需真实 VLM）；跨 imagedata 比例尺归属（P0-3）。
- F15 掩膜无专属比例尺且全图多尺有序号时 scale_level=3 的报警口径（需附录 A 修订）。
- P0-4 "禁坐标距离"适用范围的三层次澄清（文档先行）。
- CI 上的 examples 数据回归（examples 不入库，需校验和清单/内部制品方案）。
- ReviewTaskRow 外键级联与 claim_figure 的 SKIP LOCKED（PG 生产路径）。

### 9.4 验证命令

```bash
.venv/Scripts/python -m pytest tests --cov=archaeopairs --cov-fail-under=80   # 100 通过，92.46%
.venv/Scripts/python -m ruff check src tests                                  # 全绿
.venv/Scripts/python -m mypy src                                              # 全绿
.venv/Scripts/python -m archaeopairs.cli run-book --book 万州瓦子坪 --examples examples/
```

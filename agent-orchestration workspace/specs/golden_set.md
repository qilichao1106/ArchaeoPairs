# 黄金样例（V1.0）

> 目的：给真书批跑一个可机检 + 可目检的最小基线。不追求覆盖全部书，先锁住
> 三种线型的代表图和附录 A 的三个样例。

## 机检项（每次批跑后执行）

```bash
python "agent-orchestration workspace/中间过程数据和脚本/audit_run.py" <run_dir>
```

必须满足：

- `problems` 为空（无缺图、无重名、无 L1 视图/序号复用、无 <800 ink 的垃圾图）；
- 每个 L1 图：`seq/view` 一对一（同一 artifact 多视图合并除外）；
- 每个 Pair 都有 `artifact_id`，且名称中包含 `artifact_id`（冒号换 `-`）；
- 状态分布写入 `collab/DIGEST.md`。

## 代表图

| 线 | 书 / 图 | 期望 |
|---|---|---|
| L1 | `万州瓦子坪/media/image9.jpg` | 6 Pair；seq 1–6 → `2004CWWM11:5/7/8/2/4/6`；单尺 `0 4厘米` 绑到全部 Unit；名称 陶鼎/陶盒/陶壶/陶豆/陶勺/陶斗 |
| L1 | `万州瓦子坪/media/image11.jpg` | 4 Pair；seq 1–4 → `2001CWWM1:1/6/2/4`；单尺共享；名称 灰陶罐/灰陶盖罐/红陶罐/陶钵 |
| L1 | `万州瓦子坪/media/image14.jpg` | 8 Pair；seq 1–8 → `2001CWWM6:2/3/4/5/8/10/6/9`；单尺共享；名称来自图注 |
| L2 | `后屯墓地（战国卷）上册/media/image62.jpg` | 1 Pair；`M559:1`；命名序号段 `01`；整图含 `0 6厘米` 尺；`no_scale` 不得出现 |
| L3 | `后蜀赵廷隐墓发掘报告/media/image777.jpg` | 1 Pair；`M1:58-16`；命名序号段 `01`；整图输出；允许 `no_scale` |

## 目检项

- L1 成图：白底、纯平移、四周留白、比例尺在底部且尺线完整、序号数字不得出现在成图里；
- L2/L3：整图内容与原图一致（只允许白边），版图颜色不变；
- 复核项：`status=review` 的 Pair 必须有明确 `quality_flags`（`no_text` / `no_scale` / `shared_image` 等），不得静默输出。

## 变更规则

- 改分割、序号识别、比例尺裁切、命名或成图逻辑时，先跑本黄金集；
- 通过后把当次 run 目录与 `audit_run.py` 输出贴到 `collab/DIGEST.md` 之外的证据位置（`artifacts/golden/`），不覆盖历史证据。
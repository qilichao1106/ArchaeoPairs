"""S6 组装器（§4.6）。Node: 三链仲裁 + 组装成图（仲裁职责自原 S5 并入）。

流水线（§4.6.3 / extract 原型 E1–E5）：
  三链仲裁 → E1 原子构建 → E2 序号绑定 → E3 视图归组 → E4 比例尺归属 → E5 掩膜合成。

三链仲裁（原 S5 融合仲裁，V0.5.4 并入）：seq→多 artifact（同号/区间拆 Pair）；
链①⇄③序号硬匹配与冲突检测；按降级矩阵判定；图题器物号兜底（§2.2.5，弱链①
封顶 × 0.8）。seq_missing（E005）触发点自 V0.5.4 起在 s6_compose：判定后直接转
PENDING_REVIEW（经 S10 桥接 Label Studio 复核），不再进入 S4–S6 迭代回环。

E1–E5（P0 确定性实现，extract 原型的真实 CV 流程见 agents/extract/）：
  E1 原子构建：S4 原子掩膜直通（seq_id 归一）；
  E2 序号绑定：无号原子按链③序号 bbox 中心落入掩膜 bbox 绑定，冲突登记不猜测；
  E3 视图归组：同 seq_id 视图共享归属（成组信息入 provenance，S8 按 seq 拆 Pair）；
  E4 比例尺归属：三级规则（§5.4 硬匹配 > 全局共享 > 报警），说明文字并入掩膜；
  E5 掩膜合成：定稿掩膜三件套（成图像素合成由 S8 经 compositor 落对象存储）。
"""
from __future__ import annotations

from typing import cast

from ..state import FusedMapping
from . import Services
from .alarms import _note_seqs, _ocr_seqs, assign_scales, detect_alarms

# 图题兜底置信折扣：图题为描述性来源，弱于链①显式声明（§2.2.5）
CAPTION_CONF_FACTOR = 0.8


def _case(note_items: list[dict]) -> str:
    if not note_items:
        return "seq_missing"
    arts = {a for it in note_items for a in it["artifact_ids"]}
    multi = any(len(it["artifact_ids"]) > 1 for it in note_items)
    has_range = any("~" in it["seq"] for it in note_items)  # seq 已经 normalize
    total_seqs = sum(len(it["seq_list"] or [it["seq"]]) for it in note_items)
    if multi and has_range:
        return "range_split"
    if multi:
        return "split_same_seq"
    if len(arts) == 1 and total_seqs > 1:
        return "rule_b"
    return "rule_a"


def _zip_seqs_arts(seqs: list, arts: list[str], conflicts: list[str]) -> list[tuple]:
    """位置对应配对（禁笛卡尔积）：
    * 等长 → zip；
    * 单 seq 多 artifact → 同号多器，逐 artifact 拆 Pair（共享掩膜）；
    * 多 seq 单 artifact → 同器多视图（rule_b 语义）；
    * 其余数量不一致 → 冲突登记，不猜测。
    """
    if len(seqs) == len(arts):
        return list(zip(seqs, arts))
    if len(seqs) == 1:
        return [(seqs[0], a) for a in arts]
    if len(arts) == 1:
        return [(s, arts[0]) for s in seqs]
    conflicts.append(f"seq_art_mismatch:seqs={seqs},arts={arts}")
    return []


def _arbitrate(state: dict) -> tuple[dict, str, float, bool, list[str]]:
    """三链仲裁（原 S5 融合仲裁逻辑）→ (fused, case_type, confidence, degraded, alarms)。"""
    note_items = state.get("note_items", [])
    seq_ann = state.get("seq_annotations", [])
    text_art = state.get("text_artifacts", [])
    caption_arts = state.get("caption_artifacts") or []
    chains = (bool(note_items), bool(text_art), bool(seq_ann))

    alarms = detect_alarms(state)
    conflicts: list[str] = []
    serial_anomalies = state.get("serial_anomalies") or []
    conflicts.extend(f"serial_check:{a}" for a in serial_anomalies)

    # seq -> [artifacts]（多值，不截断；位置对应）
    seq_to_arts: dict[str, list[str]] = {}
    for it in note_items:
        seqs = it["seq_list"] or [it["seq"]]
        for s, a in _zip_seqs_arts(list(seqs), list(it["artifact_ids"]), conflicts):
            seq_to_arts.setdefault(str(s), []).append(a)

    # 链① vs 链③ 冲突
    if note_items and seq_ann:
        nseq, oseq = _note_seqs(note_items), _ocr_seqs(seq_ann)
        conflicts.extend(sorted(nseq ^ oseq))

    # 图题器物号兜底（§2.2.5）：图注解析不出器物号时才采用图题来源
    use_caption = bool(caption_arts) and not any(it.get("artifact_ids") for it in note_items)
    caption_unique: list[str] = []
    if use_caption:
        caption_unique = list(dict.fromkeys(caption_arts))
        note_seqs = _note_seqs(note_items)
        if len(caption_unique) == 1 and len(note_seqs) <= 1:
            case = cast(str, "rule_b")  # 整图归属该器（含单视图退化形）
        else:
            # 多器物号无序号可绑，或图注序号声明冲突 → 禁猜测，人工复核
            case = cast(str, "seq_missing")
            conflicts.append(f"caption_multi_artifacts:{','.join(caption_unique)}")
            if "E005" not in alarms:
                alarms.append("E005")
    else:
        caption_unique = []
        case = cast(str, _case(note_items))

    # 置信：图题兜底按弱链①计入链组合，封顶 × CAPTION_CONF_FACTOR
    eff = (chains[0] or use_caption, chains[1], chains[2])
    key = "".join("1" if c else "0" for c in eff)
    conf_map = {"111": 0.95, "110": 0.85, "101": 0.85, "100": 0.85,
                "011": 0.70, "010": 0.60, "001": 0.50}
    conf = conf_map.get(key, 0.5)
    if use_caption:
        conf = round(conf * CAPTION_CONF_FACTOR, 2)
    # 图注整图缺失但有链②/③或图题兜底 → 降级（不硬报警），置信封顶
    degraded = (not note_items) and (bool(text_art) or bool(seq_ann) or use_caption)
    fused = FusedMapping(seq_to_artifacts=seq_to_arts, caption_artifacts=caption_unique,
                         case_type=case, available_chains=chains, confidence=conf,
                         conflicts=conflicts)
    return fused.model_dump(), case, conf, degraded, alarms


def _bind_labels(atoms: list[dict], seq_annotations: list[dict],
                 conflicts: list[str]) -> list[dict]:
    """E2 序号绑定：无号原子按链③序号 bbox 中心落入原子 bbox 绑定（禁猜测）。

    已带号原子（mock 便捷绑定提示/复核回灌）保留原号；绑定不上的无号原子
    保持 seq_id=None，由 S8 转复核（unmapped_mask），不静默丢弃。
    """
    anns = [a for a in seq_annotations if str(a.get("text", "")).strip().isdigit()]
    for m in atoms:
        if m.get("seq_id"):
            continue
        x0, y0, x1, y1 = m.get("bbox", (0, 0, 0, 0))
        hits: list[str] = []
        for a in anns:
            ax0, ay0, ax1, ay1 = a.get("bbox", (0, 0, 0, 0))
            cx, cy = (ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                hits.append(str(a["text"]))
        if len(hits) == 1:
            m["seq_id"] = hits[0]
        elif len(hits) > 1:
            conflicts.append(f"ambiguous_bind:mask@{m.get('bbox')}:{hits}")
    return atoms


def _group_views(atoms: list[dict]) -> list[dict]:
    """E3 视图归组：同 seq_id 视图共享归属（P0 按同号成组；真实 CV 归组
    并查集 G1–G4 见 extract 原型）。"""
    return atoms


def _merge_text_scale_masks(masks: list[dict], seq_annotations: list[dict],
                            scale_annotations: list[dict]) -> list[dict]:
    """E4/E5 按 seq 归属，将说明文字与比例尺区域并入线图掩膜（掩膜三件套）。"""
    for mask in masks:
        seq = str(mask.get("seq_id")) if mask.get("seq_id") is not None else None
        text_regions = []
        for ann in seq_annotations:
            group = ann.get("group") or []
            ann_text = str(ann.get("text", "")).strip().rstrip(".")
            if ann_text == seq or (seq in group):
                text_regions.append(ann)
        scale_regions = [ann for ann in scale_annotations if str(ann.get("seq_ref")) == seq]
        if not scale_regions and mask.get("scale_level") == 2:
            scale_regions = [ann for ann in scale_annotations if not ann.get("seq_ref")]
        mask["aux_regions"] = {"text": text_regions, "scale": scale_regions}
        mask["note_text_region"] = " ".join(a.get("text", "") for a in text_regions) or None
    return masks


def run(state: dict, svc: Services) -> dict:
    fused, case, conf, degraded, alarms = _arbitrate(state)
    atoms = [dict(m) for m in (state.get("atom_masks") or [])]
    conflicts = fused.get("conflicts", [])

    # 序号绑定 + 视图归组 + 比例尺归属（E2/E3/E4）
    atoms = _bind_labels(atoms, state.get("seq_annotations", []), conflicts)
    atoms = _group_views(atoms)
    seqs = [str(m.get("seq_id")) for m in atoms if m.get("seq_id")]
    scale_map, scale_alarms = assign_scales(state.get("scale_annotations", []), seqs)
    hard = {v for v in scale_map.values() if v != "shared"}
    shared = "shared" in scale_map.values()
    for m in atoms:
        m["scale_level"] = 1 if str(m.get("seq_id")) in hard else 2 if shared else 3
    atoms = _merge_text_scale_masks(
        atoms, state.get("seq_annotations", []), state.get("scale_annotations", [])
    )
    if svc.flags.rotation_correct and state.get("orientation") == "v":
        for m in atoms:
            m["rotation"] = "cw"
    fused["conflicts"] = conflicts
    # 合并上游已有报警（如 S4 E006 经统一异常拦截置 PENDING_REVIEW 继续串行至此）
    alarms = sorted(set(state.get("alarms") or []) | set(alarms) | set(scale_alarms))

    # 报警即停 / seq_missing（E005）→ PENDING_REVIEW（复核，不回环）
    pending = (bool(alarms) or (case == "seq_missing" and not degraded)
               or state.get("status") == "PENDING_REVIEW")
    status = "PENDING_REVIEW" if pending else "COMPOSED"
    return {"fused": fused, "case_type": case, "confidence": conf, "degraded": degraded,
            "alarms": alarms, "atom_masks": atoms, "status": status}

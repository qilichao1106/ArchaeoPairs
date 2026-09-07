"""S6 组装器（§4.6）。Node: 三链仲裁 + 组装成图（仲裁职责自原 S5 并入）。

流水线（§4.6.3 / extract 原型 E1–E5）：
  三链仲裁 → E1 原子构建 → E2 序号绑定 → E3 视图归组 → E4 比例尺归属 → E5 掩膜合成。

三链仲裁（原 S5 融合仲裁，V0.5.4 并入）：seq→多 artifact（同号/区间拆 Pair）；
链①⇄③序号硬匹配与冲突检测；按降级矩阵判定；图题器物号兜底（§2.2.5，弱链①
封顶 × 0.8）。seq_missing（E005）触发点自 V0.5.4 起在 s6_compose：判定后直接转
PENDING_REVIEW（经 S10 桥接 Label Studio 复核），不再进入 S4–S6 迭代回环。

真实路径（V0.5.4，state.vision_units 非 None 时走 _run_real）：E1–E4 由
vision/assembly（extract 原型迁移）执行——build_assembly(R1 救援/R2 吸收) →
vl_review(E1.5) → bind_labels(E2 rank0-4) → rescue_missing_serials(E2.5) →
group_views(E3 G1-G4 并查集) → bind_scales(E4 L1/L2/L3)。写回终态 atom_masks
（每存活视图一个 MaskRecord）+ view_groups（组级成员/绑定信息，S8 按组发射）；
E4 绑定回填 scale_annotations.seq_ref。VL 三态策略（vl_strict）：决定性门
（E1.5 悬而未决/E3 G3-G4 歧义放弃/E4 L3 读不出）None → E007；尽力门 None/
原型信息性报警 → conflicts 可见不阻断；vl=None（无 key/--no-vl）纯 CV 记
vl_disabled。

E1–E5（P0 mock 实现，vision_units 未置）：
  E1 原子构建：S4 原子掩膜直通（seq_id 归一）；
  E2 序号绑定：无号原子按链③序号 bbox 中心落入掩膜 bbox 绑定，冲突登记不猜测；
  E3 视图归组：同 seq_id 视图共享归属（成组信息入 provenance，S8 按 seq 拆 Pair）；
  E4 比例尺归属：三级规则（§5.4 硬匹配 > 全局共享 > 报警），说明文字并入掩膜；
  E5 掩膜合成：定稿掩膜三件套（成图像素合成由 S8 经 compositor 落对象存储）。
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2

from ..errors import E1000ServiceUnavailableError
from ..state import FusedMapping
from ..vision import (
    AssemblyConfig,
    ComposeConfig,
    bind_labels,
    bind_scales,
    build_assembly,
    extract_contours,
    group_render_context,
    group_views,
    ink_mask,
    load_image,
    rescue_missing_serials,
    rle_encode,
    vl_review,
)
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


def _arbitrate(state: dict, *, skip_scale_alarms: bool = False) -> tuple[dict, str, float, bool, list[str]]:
    """三链仲裁（原 S5 融合仲裁逻辑）→ (fused, case_type, confidence, degraded, alarms)。

    skip_scale_alarms=True（真实路径）：detect_alarms 跳过 E003/E004 比例尺段，
    该段报警改由 bind_scales 产出的 e4_alarms 经 _assembly_alarm_map 映射，
    避免"白算一次再过滤"（V0.5.6）。默认 False 保持 mock 路径行为不变。
    """
    note_items = state.get("note_items", [])
    seq_ann = state.get("seq_annotations", [])
    text_art = state.get("text_artifacts", [])
    caption_arts = state.get("caption_artifacts") or []
    chains = (bool(note_items), bool(text_art), bool(seq_ann))

    alarms = detect_alarms(state, skip_scale=skip_scale_alarms)
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
    # 真实组装路径：S5 真实 OCR（PaddleOCRReader）透传 vision_units 时启用；
    # mock 链路不置 → 现有契约实现（E2 中心绑定/E3 恒等/E4 assign_scales）
    if state.get("vision_units") is not None:
        return _run_real(state, svc)
    return _run_mock_path(state, svc)


def _run_mock_path(state: dict, svc: Services) -> dict:
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


# ---------------------------------------------------------------------------
# 真实组装路径（V0.5.4）：vision/assembly E1–E4（extract 原型迁移）
# ---------------------------------------------------------------------------
def _resolve_image(state: dict) -> str:
    """图版像素绝对路径（与 S4 同模式：image_base/fileref 拼接）。"""
    image_ref = state["fileref"]
    if state.get("image_base"):
        _p = Path(state["image_base"]) / state["fileref"]
        if _p.is_file():
            image_ref = str(_p)
    return image_ref


def _assembly_alarm_map(e15_alarms, e3_stats, e4_alarms, vl_strict, vl_enabled):
    """E1.5/E3/E4 原型报警 → (E 码, conflicts 可见项)。

    决定性门 VL 悬而未决（E1.5 vl_verdict_unresolved / E3 G3·G4 歧义放弃 /
    E4 L3 读不出）→ vl_strict 下 E007；信息性报警（细长杆/小圆歧义/视图判否/
    组无尺）不占 E 码，进 conflicts 可见不阻断；比例尺放弃绑定 → E004
    （对应三级规则第三级）。vl_enabled=False（无 key/--no-vl 纯 CV）时
    "vl disabled" 不算悬而未决：规则结果生效，不触发决定性门。
    """
    codes: list[str] = []
    conflicts: list[str] = []
    decisive = False
    for a in e15_alarms:
        tag = f"{a.get('code')}:{a.get('bbox')}"
        conflicts.append(tag)
        if a.get("code") == "vl_verdict_unresolved":
            decisive = True
    g3 = (e3_stats or {}).get("g3_vl_unresolved") or 0
    g4 = (e3_stats or {}).get("g4_vl_unresolved") or 0
    if g3 or g4:
        if vl_enabled:
            decisive = True
        conflicts.append(f"e3_vl_unresolved:g3={g3},g4={g4}")
    for a in e4_alarms:
        if a.get("code") == "scale_unbound":
            conflicts.append(f"scale_unbound:{a.get('scale_id')}")
            codes.append("E004")
            if a.get("vl_unresolved") and vl_enabled:
                decisive = True          # L3 读不出（VL 不可用）→ 决定性门
        else:
            conflicts.append(f"{a.get('code')}:{a.get('group')}")
    if decisive and vl_strict:
        codes.append("E007")
    return codes, conflicts


def _run_real(state: dict, svc: Services) -> dict:
    """E1–E4 真实组装：E1.5→E2→E2.5→E3→E4 全链 + 终态写回。

    写回：atom_masks（每存活视图一个 MaskRecord，S4 原子掩膜作废重定稿）、
    view_groups（[{group_id, mask_idxs, seq_ids, scale_sis}]，S8 按组发射）、
    scale_annotations.seq_ref（E4 绑定回填：单 seq → 序号，多 seq → 'shared'）。
    """
    image_ref = _resolve_image(state)
    try:
        bgr, _ = load_image(image_ref)   # 中文路径安全
    except OSError as e:
        raise E1000ServiceUnavailableError(
            f"s6 assembly: 图片不可读 {image_ref} ({e})", service="sam") from e
    if bgr is None:
        raise E1000ServiceUnavailableError(
            f"s6 assembly: 图片解码失败 {image_ref}", service="sam")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    rec = state["vision_units"]
    cp = rec.get("contour_params") or {}
    # 与 S5 识别同参重跑轮廓（毫秒级）：rec 的 figures/bars bbox 才能按
    # bbox 精确命中轮廓索引取填充掩膜（build_assembly 契约）
    kept, _removed, _bin = extract_contours(
        gray, cp.get("dilate_k", 5), cp.get("min_area", 15.0))

    vl = svc.vl_arbiter
    cfg = AssemblyConfig(**(svc.assembly_params or {}))
    at = build_assembly(bgr, kept, rec, vl=vl, cfg=cfg)
    e15_alarms = vl_review(at, vl)
    bind_labels(at, cfg)
    rescue_missing_serials(at, vl)
    groups, _merge_log = group_views(at, vl=vl, cfg=cfg)
    bound, scale_records, e4_alarms = bind_scales(at, groups, vl=vl, cfg=cfg)

    # 三链仲裁保留为 seq→artifact 层；比例尺 E003/E004 改由真实 E4 产出
    # （bind_scales.e4_alarms 经 _assembly_alarm_map 映射）——detect_alarms
    # 传 skip_scale=True 直接跳过该段，不再"白算一次再过滤"（V0.5.6）
    fused, case, conf, degraded, chain_alarms = _arbitrate(
        state, skip_scale_alarms=True)
    codes, asm_conflicts = _assembly_alarm_map(
        e15_alarms, at.get("e3_stats"), e4_alarms,
        vl_strict=bool(getattr(vl, "strict", True)), vl_enabled=vl is not None)
    conflicts = list(fused.get("conflicts", [])) + asm_conflicts
    if vl is None:
        conflicts.append("vl_disabled")   # 无 key/--no-vl：可见不阻断

    # E4 绑定回填 scale_annotations（PaddleOCRReader 与 units.scales 同序）
    scale_annotations = [dict(s) for s in (state.get("scale_annotations") or [])]
    views = at["views"]
    group_seqs = [sorted({no for i in g for no in views[i]["label_nos"]
                          if no.isdigit()}, key=int) for g in groups]
    si_seqs: dict[int, set[str]] = {}
    for gi, binds in enumerate(bound):
        for b in binds:
            si_seqs.setdefault(b["si"], set()).update(group_seqs[gi])
    for si, seqs in si_seqs.items():
        if si < len(scale_annotations):
            scale_annotations[si]["seq_ref"] = (
                sorted(seqs)[0] if len(seqs) == 1 else "shared")

    # 终态 atom_masks（按组序连续排列，view_groups.mask_idxs 直索引）
    atom_masks: list[dict] = []
    view_groups: list[dict] = []
    rotate = svc.flags.rotation_correct and state.get("orientation") == "v"
    compose_cfg = ComposeConfig(**(svc.compose_params or {}))
    for gi, g in enumerate(groups):
        binds = bound[gi]
        level = 1 if any(b["source"] in ("L1_prefix", "L3_vl") for b in binds) \
            else 2 if any(b["source"] == "L2_unique_shared" for b in binds) else 3
        # E5 几何决策在此（组装上下文 at 只存在于本节点）：防串染内容掩膜 +
        # 组内连接符/贴近文字 + 比例尺裁条，RLE 化随组写回（S8 经
        # PixelCompositor 纯像素渲染）
        render = group_render_context(at, g, binds, cfg=compose_cfg)
        scale_texts = [scale_records[b["si"]].get("text", "")
                       for b in binds if b["si"] < len(scale_records)]
        mask_idxs: list[int] = []
        for i in g:
            v = views[i]
            mask = v.get("mask")
            if mask is None or not mask.any():
                mask = ink_mask(at["binary"], v["bbox"], pad=2)  # 墨迹兜底
            if mask is None or not mask.any():
                conflicts.append(f"view_mask_empty:{v['bbox']}")
                continue
            seq_id = str(v["label_nos"][0]) if v["label_nos"] else None
            note_text = None
            if seq_id:
                texts = [str(a.get("text", "")).strip()
                         for a in (state.get("seq_annotations") or [])
                         if str(a.get("text", "")).strip() == seq_id]
                note_text = " ".join(t for t in texts if t) or None
            atom_masks.append({
                "mask_rle": rle_encode(mask),
                "bbox": tuple(int(x) for x in v["bbox"]),
                "area": int(mask.sum()),
                "seq_id": seq_id,
                "artifact_id": None,     # 发射时经 fused.seq_to_artifacts 查
                "note_text_region": note_text,
                "scale_level": level,
                "incomplete": False,
                "aux_regions": {"scale": scale_texts} if scale_texts else {},
                "rotation": "cw" if rotate else None,
            })
            mask_idxs.append(len(atom_masks) - 1)
        view_groups.append({
            "group_id": gi,
            "mask_idxs": mask_idxs,
            "seq_ids": group_seqs[gi],
            "scale_sis": [b["si"] for b in binds],
            "render": render,
        })

    # 报警即停 / seq_missing（E005）→ PENDING_REVIEW（复核，不回环）
    alarms = sorted(set(state.get("alarms") or [])
                    | set(chain_alarms) | set(codes))
    fused["conflicts"] = conflicts
    pending = (bool(alarms) or (case == "seq_missing" and not degraded)
               or state.get("status") == "PENDING_REVIEW")
    status = "PENDING_REVIEW" if pending else "COMPOSED"
    return {"fused": fused, "case_type": case, "confidence": conf,
            "degraded": degraded, "alarms": alarms, "atom_masks": atom_masks,
            "view_groups": view_groups, "scale_annotations": scale_annotations,
            "status": status}

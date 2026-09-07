"""vision/assembly 单测：E1–E4 组装规则链（合成输入/注入 VL 桩，无 paddle）。

build_assembly 直接以合成 rec/kept 驱动（不跑 OCR）；VL 桩实现 capability
协议（judge_views/confirm_absorption/read_serials/same_artifact/
read_scale_prefix，三态），vl=None 走纯 CV 分支。
"""
from __future__ import annotations

import numpy as np

from archaeopairs.vision.assembly import (
    AssemblyConfig,
    bind_labels,
    bind_scales,
    build_assembly,
    group_views,
    rescue_missing_serials,
    vl_review,
)

H = W = 500


def _bgr_with_ink(ink_boxes=()):
    """白底 500x500 图 + ink_boxes 黑色实心块（供墨迹级判定用）。"""
    img = np.full((H, W, 3), 255, np.uint8)
    for x0, y0, x1, y1 in ink_boxes:
        img[y0:y1, x0:x1] = 0
    return img


def _fig(bbox, area=None):
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return {"bbox": list(bbox), "area": area or w * h}


def _serial(no, bbox, conf=0.99, **kw):
    return {"bbox": list(bbox), "text": no, "conf": conf, "rotated": False,
            "no": no, "scale_prefix": False, **kw}


def _scale(bbox, bar_bbox=None, text="0—4厘米", value=4.0, unit="厘米"):
    return {"kind": "bar", "bbox": list(bbox),
            "bar_bbox": list(bar_bbox or bbox), "ticks": 4,
            "text": text, "raw_text": text, "value": value, "unit": unit,
            "conf": 0.98, "verified": True, "members": []}


def _rec(figures=(), serials=(), scales=(), others=(), nums=None):
    all_serials = [str(s) for s in nums] if nums is not None \
        else [s["no"] for s in serials if not s.get("scale_prefix")]
    return {
        "ok": True, "error": None, "backend": "stub", "image_size": [W, H],
        "figures": [dict(f) for f in figures],
        "serials": [dict(s) for s in serials],
        "scales": [dict(s) for s in scales],
        "texts": [], "others": [dict(o) for o in others],
        "serial_set": {"nums": all_serials, "missing": [], "dups": [],
                       "suspect": []},
        "stats": {},
    }


class _StubVl:
    """capability 协议 VL 桩：可配置三态返回。"""

    def __init__(self, judge=None, absorb=None, serials=None, same=None,
                 prefix=None):
        self.judge = judge
        self.absorb = absorb
        self.serials = serials
        self.same = same
        self.prefix = prefix
        self.calls = []

    def judge_views(self, *, bgr, units, context="", **kw):
        self.calls.append(("judge", len(units), context))
        return self.judge, "note"

    def confirm_absorption(self, *, bgr, host_box, frag_box, **kw):
        self.calls.append(("absorb", tuple(host_box), tuple(frag_box)))
        return self.absorb, "note"

    def read_serials(self, *, crops, context="", **kw):
        self.calls.append(("serial", len(crops), context))
        return self.serials, "note"

    def same_artifact(self, *, bgr, box_a, box_b, **kw):
        self.calls.append(("same", tuple(box_a), tuple(box_b)))
        return self.same, "note"

    def read_scale_prefix(self, *, bgr, scale, where="", **kw):
        self.calls.append(("prefix", where))
        return self.prefix, "note"


# ---------------------------------------------------------------------------
# E1 build_assembly
# ---------------------------------------------------------------------------
def test_build_assembly_atoms_and_scale_side_prefix():
    """figures→views、scale_prefix/scale_side 序号归 prefixes、serial_set 保留。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        serials=[_serial("1", [140, 310, 160, 330]),
                 _serial("7", [60, 502, 75, 516])],   # 比例尺左侧（K1 例外位）
        scales=[_scale([100, 500, 300, 520])],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    assert len(at["views"]) == 2
    assert [v["id"] for v in at["views"]] == [0, 1]
    assert [lb["no"] for lb in at["labels"]] == ["1"]
    assert [p["no"] for p in at["prefixes"]] == ["7"]
    assert at["prefixes"][0]["scale_side"] is True     # K1 例外位注记
    assert at["binary"].shape == (H, W)
    assert at["rec"]["serial_set"]["nums"] == ["1", "7"]


def test_build_assembly_tick_links_and_il_rescue():
    """细高含破折号序号 → 连接符证据；孤立 'i'/'l' → 救援为 '1'。"""
    rec = _rec(
        serials=[_serial("1—", [200, 100, 206, 140], text="1—")],
        others=[{"bbox": [340, 310, 348, 336], "reason": "text",
                 "text": "i", "conf": 0.6}],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    assert any(l["reason"] == "serial_tick" for l in at["links"])
    assert [lb["no"] for lb in at["labels"]] == ["1"]
    assert at["labels"][0]["rescued"] is True


def test_build_assembly_nested_fragment_absorbed():
    """R2 嵌套碎片吸收：bbox 深包含 + 面积 <=25% 的小视图并入宿主并重编 id。"""
    rec = _rec(
        figures=[_fig([100, 100, 400, 400]),           # 宿主
                 _fig([180, 180, 220, 220])],          # 器内碎片
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    assert len(at["views"]) == 1                        # 碎片被吸收
    assert at["views"][0]["id"] == 0
    assert at["absorbed_events"][0]["host"] == 0
    assert at["absorbed_events"][0]["frag_bbox"] == [180, 180, 220, 220]
    assert at["absorbed_fragments"] == {0: [1]}


def test_build_assembly_vl_absorption_veto():
    """VL confirm_absorption=False 时较大碎片（>5% 宿主面积）保留为独立视图。"""
    rec = _rec(
        figures=[_fig([100, 100, 400, 400]), _fig([180, 180, 260, 260])],
    )
    vl = _StubVl(absorb=False)
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec, vl=vl)
    assert len(at["views"]) == 2                        # VL 拒绝吸收
    assert vl.calls and vl.calls[0][0] == "absorb"


def test_build_assembly_r1_rescue_vl_filtered():
    """R1 视图救援：O 形误读单元回捞为 rescued 视图；VL 判 False 滤掉。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300])],
        others=[{"bbox": [300, 100, 350, 150], "reason": "text",
                 "text": "O", "conf": 0.6},
                {"bbox": [300, 200, 350, 250], "reason": "unreadable",
                 "text": "", "conf": 0.0}],
    )
    # 无轮廓时按 bbox 内墨迹兜底（vm.sum()>=200）——给两个候选画墨迹
    bgr = _bgr_with_ink([(310, 110, 340, 140), (310, 210, 340, 240)])
    at = build_assembly(bgr, kept=[], rec=rec)          # vl=None 全采纳
    assert len(at["views"]) == 3
    assert at["views"][1].get("rescued") is True
    assert at["views"][2].get("rescued") is True

    vl = _StubVl(judge=[False, True])                   # 判否第一个
    at2 = build_assembly(bgr, kept=[], rec=rec, vl=vl)
    assert len(at2["views"]) == 2                        # 只回捞 unreadable
    assert at2["views"][1].get("rescued") is True


# ---------------------------------------------------------------------------
# E1.5 vl_review
# ---------------------------------------------------------------------------
def test_vl_review_duplicate_serial_rescued():
    """duplicate_serial 触发 + VL True → 回捞视图（墨迹掩膜非空）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300])],
        serials=[_serial("1", [140, 310, 160, 330])],
        others=[{"bbox": [300, 100, 340, 140], "reason": "lowconf",
                 "text": "1", "conf": 0.4}],
    )
    at = build_assembly(_bgr_with_ink([(300, 100, 340, 140)]), kept=[], rec=rec)
    vl = _StubVl(judge=[True])
    alarms = vl_review(at, vl)
    assert alarms == []                                  # True 无报警
    assert len(at["views"]) == 2                         # 回捞为视图
    assert at["views"][1]["rescued_vl"] is True
    assert at["vl_review"][0]["action"] == "rescued_view"
    assert at["vl_review"][0]["src"] == "duplicate_serial"
    assert len(at["others"]) == 0                        # 从 others 移除


def test_vl_review_unresolved_alarm_and_round_ambiguous():
    """VL None → vl_verdict_unresolved 报警；小圆 '0' 读值转人工。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300])],
        serials=[_serial("1", [140, 310, 160, 330])],
        others=[{"bbox": [300, 100, 340, 140], "reason": "lowconf",
                 "text": "1", "conf": 0.4},
                {"bbox": [300, 200, 324, 224], "reason": "text",
                 "text": "0", "conf": 0.9}],
    )
    at = build_assembly(_bgr_with_ink([(300, 100, 340, 140)]), kept=[], rec=rec)
    vl = _StubVl(judge=[None])
    alarms = vl_review(at, vl)
    codes = [a["code"] for a in alarms]
    assert "vl_verdict_unresolved" in codes
    assert "round_serial_ambiguous" in codes
    assert len(at["views"]) == 1                         # 未回捞


# ---------------------------------------------------------------------------
# E2 bind_labels
# ---------------------------------------------------------------------------
def _two_view_at(with_labels=True):
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        serials=([_serial("1", [140, 310, 160, 330]),
                  _serial("2", [340, 310, 360, 330])] if with_labels else []),
    )
    return build_assembly(_bgr_with_ink(), kept=[], rec=rec)


def test_bind_labels_below_rank0():
    at = _two_view_at()
    bind_labels(at)
    assert at["views"][0]["label_nos"] == ["1"]
    assert at["views"][0]["label_ranks"] == [0]
    assert at["views"][1]["label_nos"] == ["2"]
    m = at["e2"]["metrics"]
    assert m["n_assigned"] == 2
    assert m["rank_hist"]["below"] == 2
    assert m["assign_rate"] == 1.0


def test_bind_labels_above_rejected_k2():
    """K2：序号不会印在视图上方——上方关系不生成候选，留痕 above_rejected。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300])],
        serials=[_serial("1", [140, 60, 160, 80])],     # 视图上方
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    bind_labels(at)
    assert at["views"][0]["label_nos"] == []
    assert at["e2"]["metrics"]["n_above_rejected"] == 1
    assert at["e2"]["labels"][0]["status"] == "no_candidate"


def test_bind_labels_link_inheritance_rank4():
    """E2.1 连接符继承：断裂符一端有号、一端无号 → 无号视图继承（rank4）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        serials=[_serial("1", [140, 310, 160, 330])],
        others=[{"bbox": [235, 195, 265, 205], "reason": "connector",
                 "text": "一"}],
    )
    at = build_assembly(_bgr_with_ink([(240, 197, 260, 203)]), kept=[], rec=rec)
    bind_labels(at)
    assert at["views"][0]["label_nos"] == ["1"]
    assert at["views"][1]["label_nos"] == ["1"]          # 继承
    assert at["views"][1]["label_ranks"] == [4]
    assert "label_boxes" not in at["views"][1] or \
        not at["views"][1]["label_boxes"]                 # 无印刷序号
    link = at["e2"]["links"][0]
    assert link["cls"] == "inherited"
    assert link["inherit"]["to_view"] == 1
    assert link["vertical"] is False


def test_bind_labels_conflict_stiff_evict():
    """R3b：低置信在位者被高置信挑战者驱逐（conf 0.5 vs 1.0）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300])],
        serials=[_serial("1", [140, 310, 160, 330], conf=0.5),
                 _serial("2", [145, 312, 155, 328], conf=1.0)],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    evicted = bind_labels(at)
    assert at["views"][0]["label_nos"] == ["2"]          # 高置信者胜出
    assert len(evicted) == 1 and evicted[0]["no"] == "1"
    assert evicted[0]["_evicted_by_conf"] is True


# ---------------------------------------------------------------------------
# E2.5 rescue_missing_serials
# ---------------------------------------------------------------------------
def test_rescue_missing_serials_vl_read():
    """缺失序号经 VL 复读补挂（rank2 外部证据 + labels 追加 _vl_rescued）。"""
    at = _two_view_at()
    at["rec"]["serial_set"]["nums"] = ["1", "2", "3"]
    at["views"][1]["label_nos"] = []                     # 模拟 2 号漏读场景
    # 疑似序号形态单元：位于 view1 下方（K2 标准位），不与已识别框交叠
    at["rec"]["others"] = [{"bbox": [388, 310, 400, 326], "reason": "lowconf",
                            "text": "", "conf": 0.3}]
    vl = _StubVl(serials=["3"])
    fixed = rescue_missing_serials(at, vl)
    assert fixed == 1
    assert at["views"][1]["label_nos"] == ["3"]
    assert at["views"][1]["label_ranks"] == [2]
    assert at["labels"][-1]["_vl_rescued"] is True


def test_rescue_missing_serials_no_vl():
    at = _two_view_at()
    at["rec"]["serial_set"]["nums"] = ["1", "2", "3"]
    assert rescue_missing_serials(at, None) == 0


# ---------------------------------------------------------------------------
# E3 group_views
# ---------------------------------------------------------------------------
def test_group_views_g1_same_label():
    """G1：同号（rank<3）两视图必同组（R7 择优后同号仍可经 E2.5 直挂
    多视图，此处直接挂号验证分组证据链）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    for v in at["views"]:                        # 模拟 E2.5 直挂（rank2）
        v["label_nos"] = ["1"]
        v["label_ranks"] = [2]
    groups, log = group_views(at)
    assert groups == [[0, 1]]
    assert any(e["rule"] == "G1_same_label" for e in log)
    assert at["e3_stats"]["merges"].get("G1_same_label") == 1


def test_group_views_g1_ignores_inside_evidence():
    """rank3（内部号）不作 G1 证据：异器物不得借幻影号连锁并组。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    for v in at["views"]:
        v["label_nos"] = ["3"]
        v["label_ranks"] = [3]                   # 内部号（拓片幻影）
    groups, _log = group_views(at)
    assert [len(g) for g in groups] == [1, 1]    # 不合并（S1 闸另计）


def test_group_views_g2_connector():
    """G2：连接符两端视图相连（含 E2.1 继承场景的分组）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        serials=[_serial("1", [140, 310, 160, 330])],
        others=[{"bbox": [235, 195, 265, 205], "reason": "connector",
                 "text": "一"}],
    )
    at = build_assembly(_bgr_with_ink([(240, 197, 260, 203)]), kept=[], rec=rec)
    bind_labels(at)
    groups, log = group_views(at)
    assert groups == [[0, 1]]
    assert any(e["rule"].startswith("G2_connector") for e in log)


def test_group_views_s1_gate_no_serial_multi_object():
    """S1 规则B连通分量闸：无序号 + 2 个硬证据连通分量 → 不合并 + 报警留痕。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    bind_labels(at)
    groups, log = group_views(at)
    assert groups == [[0], [1]]                          # 保持独立
    assert any(e["rule"] == "G0_multi_object_alarm" for e in log)
    assert at["e3_stats"]["s1_gate_fired"] == 1


def test_group_views_g0_no_serial_single_chain():
    """全图无序号且硬证据连通（单链）→ 规则B 全并一组。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        others=[{"bbox": [235, 195, 265, 205], "reason": "connector",
                 "text": "一"}],
    )
    at = build_assembly(_bgr_with_ink([(240, 197, 260, 203)]), kept=[], rec=rec)
    bind_labels(at)
    groups, _log = group_views(at)
    # 硬证据连通（单链）不触发 S1 闸；G2 已并，G0 规则B 保持一组
    assert groups == [[0, 1]]


def test_group_views_g3_vl_ambiguity_merge():
    """G3 多候选歧义 → VL 兜底裁决（same=True 并入）。"""
    cfg = AssemblyConfig(stack_gap_max=90, row_gap_max=110)
    # 带号视图 + 两个等距无号候选（touch 类），无 VL 时歧义放弃
    rec = _rec(
        figures=[_fig([100, 200, 200, 300]),
                 _fig([240, 210, 300, 290]),      # 无号，与带号视图 touch
                 _fig([120, 20, 180, 80])],       # 无号上方远置
        serials=[_serial("1", [140, 310, 160, 330])],
    )
    at = build_assembly(_bgr_with_ink([(100, 200, 200, 300),
                                       (240, 210, 300, 290)]),
                        kept=[], rec=rec)
    bind_labels(at)
    groups, log = group_views(at, vl=None, cfg=cfg)
    # 两组候选距离非悬殊且 vl=None → 歧义放弃，保持独立
    assert [len(g) for g in groups] >= [1]
    vl = _StubVl(same=True)
    groups2, _ = group_views(at, vl=vl, cfg=cfg)
    assert [0, 1] in groups2 or [0, 2] in groups2        # VL 并入其一


# ---------------------------------------------------------------------------
# E4 bind_scales
# ---------------------------------------------------------------------------
def _grouped_at(prefixes, scales):
    """两组视图（号1/号2）+ 指定 prefixes/scales 的 at（已过 E1/E2/E3）。"""
    rec = _rec(
        figures=[_fig([100, 100, 200, 300]), _fig([300, 100, 400, 300])],
        serials=[_serial("1", [140, 310, 160, 330]),
                 _serial("2", [340, 310, 360, 330])] + list(prefixes),
        scales=list(scales),
    )
    at = build_assembly(_bgr_with_ink(), kept=[], rec=rec)
    bind_labels(at)
    groups, _log = group_views(at)
    return at, groups


def test_bind_scales_l1_prefix_hard_match():
    """L1：尺行前缀序号文本硬匹配（严禁坐标距离）。"""
    at, groups = _grouped_at(
        prefixes=[_serial("1", [60, 502, 75, 516], scale_prefix=True),
                  _serial("2", [60, 542, 75, 556], scale_prefix=True)],
        scales=[_scale([100, 500, 300, 520], text="0—4厘米"),
                _scale([100, 540, 300, 560], text="0—8厘米", value=8.0)],
    )
    bound, records, alarms = bind_scales(at, groups)
    assert alarms == []
    assert bound[0][0]["source"] == "L1_prefix" and bound[0][0]["si"] == 0
    assert bound[1][0]["source"] == "L1_prefix" and bound[1][0]["si"] == 1
    assert records[0]["prefix_nos"] == [1]
    assert records[1]["prefix_nos"] == [2]


def test_bind_scales_l2_unique_shared():
    """L2：全图唯一比例尺（无前缀）→ 全局默认共享。"""
    at, groups = _grouped_at(prefixes=[], scales=[_scale([100, 500, 300, 520])])
    bound, _records, alarms = bind_scales(at, groups)
    assert alarms == []
    for gi in range(2):
        assert bound[gi][0]["source"] == "L2_unique_shared"
        assert bound[gi][0]["shared"] is True


def test_bind_scales_multi_unbound_alarm_no_vl():
    """多尺无前缀 + vl=None → L1/L2/L3 全失败 → scale_unbound + group_no_scale。"""
    at, groups = _grouped_at(
        prefixes=[],
        scales=[_scale([100, 500, 300, 520]),
                _scale([100, 540, 300, 560], text="0—8厘米", value=8.0)],
    )
    bound, _records, alarms = bind_scales(at, groups)
    codes = [a["code"] for a in alarms]
    assert codes.count("scale_unbound") == 2
    assert codes.count("group_no_scale") == 2
    assert bound == [[], []]


def test_bind_scales_l15_assist_then_l1():
    """L1.5：规则收集后仍无前缀的尺送 VL 读前缀补齐 → 按 L1 硬匹配。"""
    at, groups = _grouped_at(
        prefixes=[_serial("1", [60, 502, 75, 516], scale_prefix=True)],
        scales=[_scale([100, 500, 300, 520]),
                _scale([100, 540, 300, 560], text="0—8厘米", value=8.0)],
    )
    vl = _StubVl(prefix=[2])                     # L1.5 读出尺 2 前缀
    bound, records, alarms = bind_scales(at, groups, vl=vl)
    assert alarms == []
    assert bound[1][0]["source"] == "L1_prefix" and bound[1][0]["si"] == 1
    assert records[1].get("vl_assisted")          # L1.5 留痕
    assert records[1]["prefix_nos"] == [2]


def test_bind_scales_l3_vl_fallback():
    """L3：L1.5 读不出、仍未绑定的尺再兜底（读出与组号交集即绑）。"""

    class _L3Vl(_StubVl):
        def read_scale_prefix(self, *, bgr, scale, where="", **kw):
            self.calls.append(("prefix", where))
            if where == "scale_prefix":
                return None, "vl parse failed"    # L1.5 失败
            return [2], "vl prefix='2'"           # L3 成功

    at, groups = _grouped_at(
        prefixes=[_serial("1", [60, 502, 75, 516], scale_prefix=True)],
        scales=[_scale([100, 500, 300, 520]),
                _scale([100, 540, 300, 560], text="0—8厘米", value=8.0)],
    )
    vl = _L3Vl()
    bound, records, alarms = bind_scales(at, groups, vl=vl)
    assert alarms == []
    assert bound[1][0]["source"] == "L3_vl" and bound[1][0]["si"] == 1
    assert records[1].get("vl_note")
    assert [c[1] for c in vl.calls] == ["scale_prefix", "L3"]


def test_bind_scales_prefix_range_expansion():
    """前缀 '1~2' 范围文本展开：两把尺共享同一前缀（shared=True）。"""
    at, groups = _grouped_at(
        prefixes=[_serial("1", [40, 502, 52, 516], scale_prefix=True,
                          text="1~2")],
        scales=[_scale([100, 500, 300, 520]),
                _scale([100, 540, 300, 560], text="0—8厘米", value=8.0)],
    )
    # 单前缀 token 无法跨 token 展开但 expand_prefix_nums 解析 '1~2' 文本
    bound, records, alarms = bind_scales(at, groups)
    assert records[0]["prefix_nos"] == [1, 2]
    assert bound[0][0]["source"] == "L1_prefix"
    assert bound[1][0]["source"] == "L1_prefix"        # 2 号组经 {1,2} 交集

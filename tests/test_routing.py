"""条件边路由测试（条件边/路由表（§3.4.3）/ 图类判定器（§4.2），各分支可达）。"""
from __future__ import annotations

from langgraph.graph import END

from archaeopairs.orchestration import routing


def test_route_classify():
    # V0.5.3 恢复：multi_line → parse_text + parse_image（S3/S4 平行）主通路
    assert routing.route_classify({"image_type": "multi_line_artifact"}) == ["parse_text", "parse_image"]
    assert routing.route_classify(
        {"image_type": "single_line_artifact", "status": "CLASSIFIED_SINGLE_LINE"}) == ["parse_single"]
    assert routing.route_classify(
        {"image_type": "single_plate_artifact", "status": "CLASSIFIED_PLATE"}) == ["parse_single"]
    assert routing.route_classify({"image_type": "multi_plate_artifact"}) == [END]
    assert routing.route_classify({"image_type": "discarded"}) == [END]


def test_route_assemble():
    # S8 分流：单器物整图即 Pair → S10；多器物线图 → S9 监督终检；异常 → 复核
    assert routing.route_assemble({"image_type": "single_line_artifact", "status": "ASM_VALIDATED"}) == "bridge_review"
    assert routing.route_assemble({"image_type": "single_plate_artifact", "status": "ASM_VALIDATED"}) == "bridge_review"
    assert routing.route_assemble({"image_type": "multi_line_artifact", "status": "ASM_VALIDATED"}) == "supervise"
    assert routing.route_assemble({"image_type": "multi_line_artifact", "status": "PENDING_REVIEW"}) == "bridge_review"


def test_route_single():
    # V0.5.1 single path: S7 -> S8 -> S10（不经 S9）
    assert routing.route_single({"status": "CLASSIFIED_SINGLE_LINE"}) == "assemble"
    assert routing.route_single({"status": "CLASSIFIED_PLATE"}) == "assemble"
    assert routing.route_single({"status": "EXCLUDED"}) == END
    assert routing.route_single({"status": "PENDING_REVIEW"}) == "bridge_review"


def test_route_fuse():
    assert routing.route_fuse({"case_type": "seq_missing"}) == "bridge_review"
    assert routing.route_fuse({"case_type": "rule_a"}) == "segment"


def test_route_supervise_converged():
    assert routing.route_supervise({"diagnostic": {"defect_list": []}, "assembled": False}) == "assemble"
    assert routing.route_supervise({"diagnostic": {"defect_list": []}, "assembled": True}) == "bridge_review"


def test_route_supervise_loop():
    st = {"diagnostic": {"defect_list": [{"type": "under_seg"}]}, "assembled": False, "iteration": 0}
    assert routing.route_supervise(st, max_iteration=3, loop_enabled=True) == "segment"
    st["iteration"] = 3
    assert routing.route_supervise(st, max_iteration=3, loop_enabled=True) == "bridge_review"


def test_route_supervise_targets():
    base = {"assembled": False, "iteration": 0}
    assert routing.route_supervise({**base, "diagnostic": {"defect_list": [{"type": "ocr_miss"}]}}) == "parse_image"
    assert routing.route_supervise({**base, "diagnostic": {"defect_list": [{"type": "text_split_err"}]}}) == "parse_text"  # noqa: E501
    assert routing.route_supervise({**base, "diagnostic": {"defect_list": [{"type": "group_error"}]}}) == "assemble"


def test_route_supervise_orientation_err_routes_to_segment():
    # 评审 V0.5.1 P1：orientation_err 随 mask 缺陷组回 s6（整图旋转校正后重分割），
    # 不再落入兜底 bridge_review（文档 §3.4.3 路由表与代码行为一致）。
    st = {"diagnostic": {"defect_list": [{"type": "orientation_err"}]},
          "assembled": False, "iteration": 0}
    assert routing.route_supervise(st, max_iteration=3, loop_enabled=True) == "segment"


def test_route_supervise_no_improve_escalates():
    st = {"no_improve": True, "assembled": False, "iteration": 0,
          "diagnostic": {"defect_list": [{"type": "under_seg"}]}}
    assert routing.route_supervise(st) == "bridge_review"


def test_route_fuse_degraded_chain_continues():
    st = {"alarms": [], "case_type": "seq_missing", "degraded": True}
    assert routing.route_fuse(st) == "segment"


def test_route_fuse_seq_missing_without_evidence_reviews():
    st = {"alarms": [], "case_type": "seq_missing", "degraded": False}
    assert routing.route_fuse(st) == "bridge_review"

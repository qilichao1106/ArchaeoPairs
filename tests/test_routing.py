"""条件边路由测试（条件边/路由表（§3.4.3）/ 图类判定器（§4.2），各分支可达）。

V0.5.4：多器物线图串行 S3→S4→S5→S6；S9 纯质检门 route_qc（无修正回环，
route_fuse/route_supervise 已删除）。
"""
from __future__ import annotations

from langgraph.graph import END

from archaeopairs.orchestration import routing


def test_route_classify():
    # V0.5.4 串行：multi_line → s3_text 先行（S3→S4→S5→S6 线性边）
    assert routing.route_classify({"image_type": "multi_line_artifact"}) == ["s3_text"]
    assert routing.route_classify(
        {"image_type": "single_line_artifact", "status": "CLASSIFIED_SINGLE_LINE"}) == ["s7_single"]
    assert routing.route_classify(
        {"image_type": "single_plate_artifact", "status": "CLASSIFIED_PLATE"}) == ["s7_single"]
    assert routing.route_classify({"image_type": "multi_plate_artifact"}) == [END]
    assert routing.route_classify({"image_type": "discarded"}) == [END]


def test_route_compose():
    # S6 组装后分流：报警/seq_missing（PENDING_REVIEW）→ S10 复核桥接；否则 → S8
    assert routing.route_compose({"status": "COMPOSED"}) == "s8_assemble"
    assert routing.route_compose({"status": "PENDING_REVIEW"}) == "s10_review"
    assert routing.route_compose({"status": "COMPOSED", "alarms": ["E001"]}) == "s10_review"


def test_route_assemble():
    # S8 分流：单器物整图即 Pair → S10；多器物线图 → S9 纯质检；异常 → 复核
    assert routing.route_assemble({"image_type": "single_line_artifact", "status": "ASM_VALIDATED"}) == "s10_review"
    assert routing.route_assemble({"image_type": "single_plate_artifact", "status": "ASM_VALIDATED"}) == "s10_review"
    assert routing.route_assemble({"image_type": "multi_line_artifact", "status": "ASM_VALIDATED"}) == "s9_supervise"
    assert routing.route_assemble({"image_type": "multi_line_artifact", "status": "PENDING_REVIEW"}) == "s10_review"


def test_route_single():
    # V0.5.1 single path: S7 -> S8 -> S10（不经 S9）
    assert routing.route_single({"status": "CLASSIFIED_SINGLE_LINE"}) == "s8_assemble"
    assert routing.route_single({"status": "CLASSIFIED_PLATE"}) == "s8_assemble"
    assert routing.route_single({"status": "EXCLUDED"}) == END
    assert routing.route_single({"status": "PENDING_REVIEW"}) == "s10_review"


def test_route_qc_always_bridges_review():
    # S9 纯质检门：pass/reject 均进 S10 两级分流（输出入库 / 转复核），无自动回环
    assert routing.route_qc({"qc_report": {"qc_verdict": "pass", "defect_list": []}}) == "s10_review"
    assert routing.route_qc({"qc_report": {"qc_verdict": "reject",
                                           "defect_list": [{"type": "under_seg"}]}}) == "s10_review"

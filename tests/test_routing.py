"""条件边路由测试（§3.4.3 / 4.2，各分支可达）。"""
from __future__ import annotations

from langgraph.graph import END

from archaeopairs.orchestration import routing


def test_route_classify():
    assert routing.route_classify({"image_type": "line_drawing"}) == ["parse_text", "parse_image"]
    assert routing.route_classify({"image_type": "plate_artifact"}) == ["parse_plate"]
    assert routing.route_classify({"image_type": "discarded"}) == [END]


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

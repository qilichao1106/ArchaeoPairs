"""S8 真实组级发射（view_groups 驱动）+ PixelCompositor 真像素合成。

S6 真实路径产出（含 view_groups.render）直接喂 S8，验证：一组 1 张真 PNG
（白底+平移内容+比例尺行，非占位白图）、多器物共组逐 artifact 拆 Pair、
组 seq 无映射转复核。mock 路径（view_groups 未置）由既有契约测试覆盖。
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import cv2

from archaeopairs.agents import s6, s8
from archaeopairs.capability.compose import PixelCompositor
from archaeopairs.storage.object_store import LocalObjectStore

from test_s6_real import _real_state


def _real_services(services, tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    return dataclasses.replace(services, object_store=store,
                               compositor=PixelCompositor(store)), store


def test_group_emission_real_png(services, tmp_path):
    """单组单器：1 Pair + 1 真像素 PNG（含器物内容与比例尺行）。"""
    state = _real_state(tmp_path)
    svc, store = _real_services(services, tmp_path)
    out6 = s6.run(state, svc)
    assert out6["status"] == "COMPOSED"
    state.update(out6)
    out8 = s8.run(state, svc)
    assert out8["status"] == "ASM_VALIDATED"
    assert len(out8["pair_records"]) == 1
    rec = out8["pair_records"][0]
    assert rec["artifact_id"] == "M4:1"
    assert rec["provenance"]["views"] == 1
    assert rec["provenance"]["scale_sis"] == [0]
    # 真像素 PNG（对象存储键）：非 1x1 占位、含黑像素（视图平移+比例尺行）
    assert store.exists(rec["image_path"])
    img = cv2.imread(str(store.get(rec["image_path"])))
    assert img is not None and min(img.shape[:2]) > 8
    assert img.min() < 255


def test_group_multi_artifact_split(services, tmp_path):
    """同号多器共组：逐 artifact 拆 Pair，各 Pair 独立 PNG（共享组画面）。"""
    state = _real_state(tmp_path)
    state["note_items"] = [{"seq": "1", "seq_list": [1],
                            "artifact_ids": ["M4:1", "M4:2"]}]
    svc, store = _real_services(services, tmp_path)
    state.update(s6.run(state, svc))
    out8 = s8.run(state, svc)
    assert out8["status"] == "ASM_VALIDATED"
    arts = [r["artifact_id"] for r in out8["pair_records"]]
    assert arts == ["M4:1", "M4:2"]
    assert len({r["image_path"] for r in out8["pair_records"]}) == 2
    for r in out8["pair_records"]:
        assert store.exists(r["image_path"])


def test_group_unmapped_seq_review(services, tmp_path):
    """组 seq 无 artifact 映射：不静默丢弃 → PENDING_REVIEW(E002)。"""
    state = _real_state(tmp_path)
    state["note_items"] = [{"seq": "9", "seq_list": [9],
                            "artifact_ids": ["M4:9"]}]   # 组 seq '1' 无映射
    svc, _store = _real_services(services, tmp_path)
    state.update(s6.run(state, svc))
    out8 = s8.run(state, svc)
    assert out8["status"] == "PENDING_REVIEW"
    assert out8["alarms"] == ["E002"]
    assert out8["exclude_reason"] == "unmapped_mask"
    assert out8["pair_records"] == []


def test_group_rule_b_whole_artifact(services, tmp_path):
    """rule_b（无图注序号，单器整图归属）：组 seq 空走兜底池发射。"""
    state = _real_state(tmp_path)
    state["note_items"] = [{"seq": "1", "seq_list": [1],
                            "artifact_ids": ["M4:1"]}]
    svc, _store = _real_services(services, tmp_path)
    out6 = s6.run(state, svc)
    state.update(out6)
    # 模拟 rule_b：清空组序号绑定（图注序号不可用时整图归属）
    state["case_type"] = "rule_b"
    for g in state["view_groups"]:
        g["seq_ids"] = []
    out8 = s8.run(state, svc)
    assert out8["status"] == "ASM_VALIDATED"
    assert [r["artifact_id"] for r in out8["pair_records"]] == ["M4:1"]
    # 无序号段占位 01（§7.2）
    assert "_01_" in out8["pair_records"][0]["image_path"]


def test_pixel_compositor_mock_parity(tmp_path):
    """无 render_ctx 时与 MockCompositor 同形：masks 空+source 拷原图。"""
    from archaeopairs.capability.compose import make_white_png

    store = LocalObjectStore(tmp_path / "objects")
    comp = PixelCompositor(store)
    src = tmp_path / "src.png"
    src.write_bytes(make_white_png(20, 20))
    key = comp.compose(image_path="a.png", masks=[], trace_id="t",
                       source=str(src))
    assert Path(key).exists() and Path(key).stat().st_size > 0
    # masks 非空且无 render_ctx → 白底占位
    key2 = comp.compose(image_path="b.png", masks=[{"seq_id": "1"}],
                        trace_id="t", source=str(src))
    assert Path(key2).exists()


def test_pixel_compositor_bad_source(tmp_path):
    """render_ctx 给定但源图不可读 → E1100（统一拦截 PENDING_REVIEW）。"""
    import pytest

    from archaeopairs.errors import E1100StorageError

    store = LocalObjectStore(tmp_path / "objects")
    comp = PixelCompositor(store)
    with pytest.raises(E1100StorageError):
        comp.compose(image_path="c.png", masks=[{"seq_id": "1"}], trace_id="t",
                     source=str(tmp_path / "missing.png"),
                     render_ctx={"content_rle": "1x1:1", "content_box": [0, 0, 1, 1]})

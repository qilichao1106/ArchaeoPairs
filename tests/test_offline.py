"""最小离线运行入口测试：零模型（No-op stub 被调用即失败）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from archaeopairs.config import load_flags, load_thresholds
from archaeopairs.offline import (
    NoOpOCR,
    NoOpSAM,
    NoOpVLM,
    OfflineGateway,
    minimal_services,
    run_single_offline,
)
from archaeopairs.parsers import s1_xml


def test_noop_stubs_raise_if_called():
    """单器物路径不得触碰任何模型：stub 一旦被调用即抛错。"""
    with pytest.raises(NotImplementedError):
        NoOpVLM().classify(image_ref="x", caption="c", trace_id="t")
    with pytest.raises(NotImplementedError):
        NoOpVLM().diagnose(image_ref="x", context={}, trace_id="t")
    with pytest.raises(NotImplementedError):
        NoOpSAM().segment(image_ref="x", prompts=[], trace_id="t")
    with pytest.raises(NotImplementedError):
        NoOpOCR().read(image_ref="x", regions=[], trace_id="t")
    with pytest.raises(NotImplementedError):
        OfflineGateway().call("vlm", lambda **k: {}, figure_id="f", trace_id="t")


def test_minimal_services_has_required_fields():
    svc = minimal_services(load_thresholds(), load_flags())
    assert svc.thresholds is not None and svc.flags is not None
    assert svc.name_registry == {}
    assert svc.review_bridge is None
    assert svc.object_store is None and svc.compositor is None


def test_run_single_offline_never_touches_models(tmp_path: Path):
    """整书跑：单器物图正常 OUTPUT，且不触发任何 No-op stub（零模型）。"""
    xml = """<book>
<section>
<figure><mediaobject><imageobject><imagedata fileref="media/image1.jpg"/></imageobject></mediaobject>
<caption role="figure-title"><para role="figure-title">图一 陶豆</para></caption></figure>
<para role="figure-note">1. 陶豆（M4:1）</para>
</section>
</book>"""
    book_dir = tmp_path / "books" / "mini"
    book_dir.mkdir(parents=True)
    (book_dir / "data.xml").write_text(xml, encoding="utf-8")
    figures, ground, _ = s1_xml.parse_report(book_dir / "data.xml", "mini")
    assert len(figures) == 1

    out = run_single_offline("mini", books_dir=str(tmp_path / "books"))
    assert out["pairs"] >= 0
    assert out["statuses"]  # 每图都有状态
    # 无模型调用：run_single_offline 内部用 No-op stub，若曾发生调用会抛 NotImplementedError
    assert out["by_image_type"]


def test_run_single_offline_writes_media_copy(tmp_path: Path):
    """单器物写图：输出 PNG 为源 media 图拷贝，而非白底占位。"""
    xml = """<book>
<section>
<figure><mediaobject><imageobject><imagedata fileref="media/image1.jpg"/></imageobject></mediaobject>
<caption role="figure-title"><para role="figure-title">图一 陶豆</para></caption></figure>
<para role="figure-note">1. 陶豆（M4:1）</para>
</section>
</book>"""
    book_dir = tmp_path / "books" / "one"
    (book_dir / "media").mkdir(parents=True)
    (book_dir / "data.xml").write_text(xml, encoding="utf-8")
    src_bytes = b"\xff\xd8\xff\xe0__NOT_A_WHITE_PLACEHOLDER__"  # 伪 JPEG 特征字节
    (book_dir / "media" / "image1.jpg").write_bytes(src_bytes)

    out_dir = tmp_path / "out"
    out = run_single_offline("one", books_dir=str(tmp_path / "books"),
                             write_images=True, objects_dir=out_dir)
    assert out["pairs"] == 1
    rec = out["records"][0]
    out_png = out_dir / rec["image_path"]
    assert out_png.is_file()
    # 单器物(masks=[]) → 直接拷贝原图，落在输出目录的内容应等于源字节
    assert out_png.read_bytes() == src_bytes


def test_run_single_offline_archives_non_single(tmp_path: Path):
    """非单器物（多器物 → multi_line/skipped、无器物号 → 排除）均不产出 Pair 且不触碰模型。"""
    xml = """<book>
<section>
<figure><mediaobject><imageobject><imagedata fileref="media/image1.jpg"/></imageobject></mediaobject>
<caption role="figure-title"><para role="figure-title">图一 出土器物</para></caption></figure>
<para role="figure-note">1. 陶豆（M4:1） 2. 陶壶（M4:2）</para>
</section>
</book>"""
    book_dir = tmp_path / "books" / "multi"
    book_dir.mkdir(parents=True)
    (book_dir / "data.xml").write_text(xml, encoding="utf-8")

    out = run_single_offline("multi", books_dir=str(tmp_path / "books"))
    # 2 器物 → 多器物线图 → 试点 MULTI_LINE_SKIPPED 归档，不产出 Pair
    assert out["pairs"] == 0
    assert list(out["by_image_type"].values())  # 有判定

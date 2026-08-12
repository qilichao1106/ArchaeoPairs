"""测试公共 fixture：合成 DocBook XML + mock 服务容器。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archaeopairs.agents import Services
from archaeopairs.capability import MockOCR, MockSAM, MockVLM
from archaeopairs.capability.compose import MockCompositor
from archaeopairs.config import load_flags, load_thresholds
from archaeopairs.gateway import Gateway
from archaeopairs.integrations import MockReviewBridge
from archaeopairs.parsers import s1_xml
from archaeopairs.storage import LocalObjectStore

SYNTH_XML = """<book>
<section>
<figure><mediaobject><imageobject><imagedata fileref="media/image1.jpg"/></imageobject></mediaobject>
<caption role="figure-title"><para role="figure-title">图一 出土器物</para></caption></figure>
<para role="figure-note">1. 陶豆（M4:1） 2. 陶壶（M4:2）</para>
</section>
</book>"""


@pytest.fixture()
def synth_book(tmp_path: Path) -> tuple[list, dict, list]:
    p = tmp_path / "data.xml"
    p.write_text(SYNTH_XML, encoding="utf-8")
    return s1_xml.parse_report(p, "synth")


@pytest.fixture()
def services(synth_book) -> Services:
    _, ground, _ = synth_book
    th = load_thresholds()
    fl = load_flags()
    return Services(vlm=MockVLM(ground), sam=MockSAM(ground), ocr=MockOCR(ground),
                    gateway=Gateway(per_figure_cap_cny=th.per_figure_cap_cny),
                    thresholds=th, flags=fl)


@pytest.fixture()
def base_state(synth_book) -> dict:
    figures, ground, _ = synth_book
    fig = figures[0]
    return {
        "book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
        "caption": fig.caption, "figure_note": fig.figure_note,
        "iteration": 0, "defect_history": [], "assembled": False,
        "trace_id": "t-test", "flags": load_flags().model_dump(), "status": "INIT",
    }

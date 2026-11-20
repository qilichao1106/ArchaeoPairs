"""T-010 selfcheck: per-figure pipeline L1/L2/L3/L4 with fake OCR/writer."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from archaeopairs.models import (  # noqa: E402
    FigureInput, OcrResult, ScaleBar, SeqLabel,
)
from archaeopairs.pipeline import PipelineConfig, process_book, process_figure  # noqa: E402

LOG = Path(__file__).with_suffix(".log")


class FakeOCR:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        return self.result


class FakeWriter:
    def __init__(self):
        self.images = []
        self.pairs = []
        self.ledger = []

    def write_image(self, name, image):
        self.images.append((name, tuple(image.shape)))
        return name

    def write_pairs(self, records):
        self.pairs.extend(records)

    def write_ledger(self, rows):
        self.ledger.extend(rows)


def canvas(path, color=False):
    img = np.full((200, 300, 3), 255, np.uint8)
    boxes = [(30, 30, 90, 90), (140, 30, 200, 90)]
    for x0, y0, x1, y1 in boxes:
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), -1)
    cv2.line(img, (30, 165), (270, 165), (0, 0, 0), 2)
    if color:
        img[:, :, 2] = np.where(img[:, :, 0] < 128, 80, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)


def figure(path, caption, note, body=None):
    return FigureInput(
        book_id="bookA", figure_id="fig1", fileref=path.name,
        media_path=str(path), caption=caption, figure_note=note,
        body_paras=body or [],
    )


def l1_ocr():
    return OcrResult(
        seqs=[SeqLabel(text="1", bbox=(40, 40, 50, 50), conf=0.99),
              SeqLabel(text="2", bbox=(150, 40, 160, 50), conf=0.99)],
        scales=[ScaleBar(text="0 4厘米", bbox=(25, 155, 275, 175),
                         value=4.0, unit="厘米", prefix_nos=["1", "2"])],
        source="fake",
    )


def run():
    lines = ["T-010 selfcheck"]
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        # L1: two artifacts, one shared scale
        img = tmp / "l1.png"; canvas(img)
        note = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
        body = [{"id": "p1", "text": "陶豆标本M4:1，泥质灰陶。陶壶标本M4:2，夹砂灰陶。"}]
        fig = figure(img, "图一 出土器物", note, body)
        writer = FakeWriter()
        cfg = PipelineConfig(ocr=FakeOCR(l1_ocr()), writer=writer)
        res = process_figure(fig, cfg)
        lines.append(f"L1 status={res.status} pairs={len(res.pairs)} views_written={len(writer.images)}")
        assert res.status == "output", res.conflicts
        assert len(res.pairs) == 2, res.pairs
        assert {p.artifact_id for p in res.pairs} == {"M4:1", "M4:2"}
        assert all(p.image_path.startswith("图一_") for p in res.pairs)
        assert all(p.provenance.mapping.scale_sources == ["L1_prefix"] for p in res.pairs)
        assert len(writer.images) == 2
        assert len(writer.ledger) == 0  # process_book writes pairs/ledger
        assert not res.artifact_map.unbound_views, res.artifact_map.unbound_views

        # L2: single line, whole image
        line = tmp / "l2.png"; img2 = np.full((140, 100, 3), 255, np.uint8)
        cv2.rectangle(img2, (20, 20), (80, 120), (0, 0, 0), 1)
        cv2.imwrite(str(line), img2)
        fig2 = figure(line, "图2-1-5 铜鼎（M4:6）", None,
                      [{"id": "p1", "text": "铜鼎标本M4:6，通高10厘米。"}])
        w2 = FakeWriter()
        res2 = process_figure(fig2, PipelineConfig(writer=w2))
        lines.append(f"L2 status={res2.status} pairs={len(res2.pairs)}")
        assert res2.status == "output" and len(res2.pairs) == 1
        assert res2.pairs[0].source_role == "line"
        assert res2.pairs[0].image_path == "图2-1-5_01_M4-6.png"

        # L3: single plate, whole image
        plate = tmp / "l3.png"; canvas(plate, color=True)
        fig3 = figure(plate, "图版一 陶罐", "1. 陶罐（M4:1）",
                      [{"id": "p1", "text": "陶罐标本M4:1，泥质灰陶。"}])
        w3 = FakeWriter()
        res3 = process_figure(fig3, PipelineConfig(writer=w3))
        lines.append(f"L3 status={res3.status} pairs={len(res3.pairs)}")
        assert res3.status == "output" and len(res3.pairs) == 1
        assert res3.pairs[0].source_role == "plate"

        # L4: multi plate archived
        fig4 = figure(plate, "图版一 陶罐、陶壶", "1. 陶罐（M4:1） 2. 陶壶（M4:2）")
        res4 = process_figure(fig4, PipelineConfig(writer=FakeWriter()))
        lines.append(f"L4 status={res4.status} pairs={len(res4.pairs)}")
        assert res4.status == "excluded" and not res4.pairs

        # book-level writer calls
        wb = FakeWriter()
        results = process_book([fig, fig2], PipelineConfig(ocr=FakeOCR(l1_ocr()), writer=wb))
        lines.append(f"book results={len(results)} pairs={len(wb.pairs)} ledger={len(wb.ledger)}")
        assert len(wb.pairs) >= 3 and len(wb.ledger) >= 3

    lines.append("SELFCHECK OK")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    run()
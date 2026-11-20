"""T-012 selfcheck: real-book hardening behaviours, entirely synthetic/offline.

Covers the six frozen groups with direct helper checks plus one L1 end-to-end
run: glyph seq replacement + note names, duplicate sanitising, text ownership,
scale-box expansion, oversized-unit protection.  Run from the project root::

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-012/selfcheck_t012.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT / "src"))

from archaeopairs.models import (  # noqa: E402
    ArtifactMap, ArtifactUnit, FigureInput, OcrResult, ScaleBar, SeqLabel, View,
)
from archaeopairs.pipeline import (  # noqa: E402
    PipelineConfig, _expand_scale_boxes, _oversized_units, _sanitize_seq_labels,
    _text_owned, process_book,
)
from archaeopairs.vision import segment_views  # noqa: E402


class FakeOCR:
    def __init__(self, result, glyphs=None):
        self.result = result
        self.glyphs = glyphs
        self.calls = []
        self.glyph_calls = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        return self.result

    def read_glyphs(self, image_path, boxes):
        self.glyph_calls.append([tuple(box) for box in boxes])
        return list(self.glyphs or [])


class FakeWriter:
    def __init__(self):
        self.images = []
        self.pairs = []
        self.ledger = []

    def write_image(self, name, image):
        self.images.append(name)
        return name

    def write_pairs(self, records):
        self.pairs.extend(records)

    def write_ledger(self, rows):
        self.ledger.extend(rows)


def image(path, *, size=(300, 200), boxes=(), glyphs=(), bar=None, texts=()):
    canvas = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(canvas)
    for box in (*boxes, *glyphs, *texts):
        draw.rectangle(tuple(int(v) for v in box), fill="black")
    if bar is not None:
        draw.rectangle(tuple(int(v) for v in bar), fill="black")
    canvas.save(path)
    return path


def view(index, bbox):
    x0, y0, x1, y1 = bbox
    return View(view_id=index, bbox=bbox, area=(x1 - x0) * (y1 - y0), mask_rle="")


def figure(path, note, body):
    return FigureInput(
        book_id="bookA", figure_id="fig1", fileref=Path(path).name,
        media_path=str(path), caption="图一 出土器物", figure_note=note,
        body_paras=body,
    )


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="t012_") as raw:
        tmp = Path(raw)
        # 1. L1: glyph labels replace OCR seqs, glyph views are filtered, names set.
        path = image(
            tmp / "l1.png",
            boxes=[(100, 20, 180, 90), (230, 20, 300, 90)],
            glyphs=[(55, 30, 73, 48), (192, 30, 210, 48)],
            bar=(40, 180, 300, 183),
        )
        ocr = FakeOCR(OcrResult(
            seqs=[SeqLabel(text="9", bbox=(5, 5, 15, 15), conf=0.9)],
            scales=[ScaleBar(text="0 4厘米", bbox=(35, 175, 305, 190),
                             value=4.0, unit="厘米", prefix_nos=["1", "2"])],
            source="fake",
        ), glyphs=["1", "2"])
        writer = FakeWriter()
        result = process_book(
            [figure(path, "1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
                    [{"id": "p1", "text": "陶鼎M1:1。陶盒M1:2。"}])],
            PipelineConfig(ocr=ocr, writer=writer),
        )[0]
        assert result.status == "output", (result.status, result.conflicts)
        assert [pair.artifact_name for pair in result.pairs] == ["陶鼎", "陶盒"]
        assert [pair.provenance.mapping.seq_ids for pair in result.pairs] == [["1"], ["2"]]
        assert len(ocr.glyph_calls) == 1
        glyph_views = [v for v in segment_views(path)
                       if v.bbox[2] - v.bbox[0] <= 60 and v.bbox[3] - v.bbox[1] <= 60]
        assert ocr.glyph_calls[0] == [tuple(v.bbox) for v in glyph_views]
        views_payload = [row for row in writer.ledger if row.get("kind") == "views"][0]["payload"]
        assert len(views_payload) == 2

        # 2. Duplicate seq: only the box next to a glyph survives.
        glyph_only = view(0, (100, 100, 110, 120))
        near = SeqLabel(text="1", bbox=(112, 100, 122, 120), conf=0.9)
        far = SeqLabel(text="1", bbox=(400, 200, 410, 220), conf=0.9)
        assert _sanitize_seq_labels([near, far], [glyph_only, view(1, (300, 50, 500, 400))]) == [near]

        # 3. A large drawing survives a thin bogus text block; a glyph does not.
        assert _text_owned((100, 100, 300, 300), (150, 150, 160, 250)) is False
        assert _text_owned((100, 100, 300, 300), (100, 100, 280, 300)) is True
        assert _text_owned((100, 100, 110, 115), (80, 90, 200, 120)) is True

        # 4. A scale box grows down to the printed bar but stays put without one.
        blocks = [(40, 50, 48, 62), (52, 50, 60, 62), (66, 50, 74, 62),
                  (80, 50, 90, 62), (94, 50, 104, 62)]
        with_bar = image(tmp / "bar.png", size=(200, 120), texts=blocks,
                         bar=(30, 80, 140, 83))
        scale = ScaleBar(text="0 4厘米", bbox=(35, 45, 110, 65), prefix_nos=["1"])
        bbox = _expand_scale_boxes(with_bar, [scale])[0].bbox
        assert isinstance(bbox, tuple) and bbox[0] <= 35 and bbox[2] >= 110 and bbox[3] >= 83
        no_bar = image(tmp / "nobar.png", size=(200, 120), texts=blocks)
        assert _expand_scale_boxes(no_bar, [scale])[0].bbox == (35, 45, 110, 65)

        # 5. Union bbox above 70% of the figure is oversized.
        huge = view(0, (10, 10, 600, 600))
        union = view(1, (400, 400, 990, 990))
        amap = ArtifactMap(book_id="bookA", figure_id="fig1", units=[
            ArtifactUnit(artifact_id="M1:1", view_ids=[0, 1]),
            ArtifactUnit(artifact_id="M1:2", view_ids=[2]),
        ])
        views = [huge, union, view(2, (50, 50, 150, 150))]
        assert _oversized_units(amap, views, (1000, 1000)) == {"M1:1"}
        assert _oversized_units(amap, views, None) == set()

    print("SELFCHECK OK")


if __name__ == "__main__":
    run()
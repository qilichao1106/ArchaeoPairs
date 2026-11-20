"""T-013 selfcheck: scales-only priority, retry budget, glyph fallback, legend band.

Entirely synthetic/offline.  Run from the project root::

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-013/selfcheck_t013.py
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
    FigureInput,
    OcrResult,
    ScaleBar,
    SeqLabel,
    TextBlock,
    View,
)
from archaeopairs.pipeline import (  # noqa: E402
    PipelineConfig,
    _filter_aux_views,
    process_book,
)

BOXES = [(100, 20, 180, 90), (230, 20, 300, 90)]
GLYPHS = [(55, 30, 73, 48), (252, 100, 270, 118)]
SCALE = ScaleBar(text="0 4厘米", bbox=(35, 175, 305, 190), value=4.0,
                 unit="厘米", prefix_nos=["1", "2"])
SEQS = [SeqLabel(text=t, bbox=b, conf=0.99) for t, b in zip(["1", "2"], GLYPHS)]


class PlainOCR:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def read(self, path):
        self.calls.append(str(path))
        return self.result


class FakeOCR:
    def __init__(self, scale_script=(), glyphs=None, glyph_error=None, full=None):
        self.scale_script = list(scale_script)
        self.glyphs = glyphs
        self.glyph_error = glyph_error
        self.full = full if full is not None else OcrResult()
        self.scale_calls, self.read_calls, self.glyph_calls = [], [], []

    def read(self, path):
        self.read_calls.append(str(path))
        return self.full

    def read_scales(self, path):
        self.scale_calls.append(str(path))
        if not self.scale_script:
            raise AssertionError("read_scales called more often than scripted")
        item = self.scale_script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def read_glyphs(self, path, boxes):
        self.glyph_calls.append([tuple(b) for b in boxes])
        if self.glyph_error is not None:
            raise self.glyph_error
        return list(self.glyphs or [])


class FakeWriter:
    def __init__(self):
        self.images, self.pairs, self.ledger = [], [], []

    def write_image(self, name, image):
        self.images.append(name)
        return name

    def write_pairs(self, records):
        self.pairs.extend(records)

    def write_ledger(self, rows):
        self.ledger.extend(rows)


def image(path):
    canvas = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(canvas)
    for box in (*BOXES, *GLYPHS):
        draw.rectangle(tuple(int(v) for v in box), fill="black")
    canvas.save(path)
    return str(path)


def run(path, provider):
    fig = FigureInput(
        book_id="bookA", figure_id="fig1", fileref=Path(path).name,
        media_path=path, caption="图一 出土器物",
        figure_note="1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
        body_paras=[{"id": "p1", "text": "陶鼎标本M1:1，泥质灰陶。"},
                    {"id": "p2", "text": "陶盒标本M1:2，泥质灰陶。"}],
    )
    writer = FakeWriter()
    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]
    return result, writer


def ocr_payload(writer):
    return [row for row in writer.ledger if row.get("kind") == "ocr"][0]["payload"]


def checks() -> None:
    with tempfile.TemporaryDirectory(prefix="t013_") as raw:
        path = image(Path(raw) / "l1.png")
        text = TextBlock(text="比例尺", bbox=(200, 180, 260, 190))

        # 1+2. scales-only priority; seqs from glyphs, scales/texts from read_scales.
        ocr = FakeOCR([OcrResult(scales=[SCALE], texts=[text], source="scale")],
                      glyphs=["1", "2"],
                      full=OcrResult(seqs=SEQS, scales=[SCALE], source="full"))
        result, writer = run(path, ocr)
        assert result.status == "output"
        assert [p.provenance.mapping.seq_ids for p in result.pairs] == [["1"], ["2"]]
        assert ocr.scale_calls == [path] and ocr.read_calls == []
        payload = ocr_payload(writer)
        assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]
        assert payload["texts"] == [text.model_dump()]

        # 2. A read-only provider falls back to full read like T-010.
        plain = PlainOCR(OcrResult(seqs=SEQS, scales=[SCALE], source="paddle"))
        result, _ = run(path, plain)
        assert plain.calls == [path] and result.status == "output"
        assert len(result.pairs) == 2

        # 3. Retry exactly once when the first scale read misses.
        retried = FakeOCR([OcrResult(), OcrResult(scales=[SCALE])], glyphs=["1", "2"])
        result, _ = run(path, retried)
        assert result.status == "output" and retried.scale_calls == [path, path]

        # 3. Two empty scale reads stop at two and go to no-scale review.
        empty = FakeOCR([OcrResult(), OcrResult()], glyphs=["1", "2"])
        result, writer = run(path, empty)
        assert result.status == "pending_review" and result.alarms == ["E007"]
        assert empty.scale_calls == [path, path] and writer.images == []

        # 3. A first-pass hit is never retried.
        hit = FakeOCR([OcrResult(scales=[SCALE])], glyphs=["1", "2"])
        result, _ = run(path, hit)
        assert result.status == "output" and hit.scale_calls == [path]

        # 4. Empty glyph grid -> one full read for seqs; scales stay from pass one.
        fallback = FakeOCR([OcrResult(scales=[SCALE])], glyphs=[], full=OcrResult(
            seqs=SEQS, scales=[ScaleBar(text="0 9厘米", bbox=(35, 175, 305, 190))]))
        result, writer = run(path, fallback)
        assert fallback.read_calls == [path] and fallback.scale_calls == [path]
        payload = ocr_payload(writer)
        assert [item["text"] for item in payload["seqs"]] == ["1", "2"]
        assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]

        # 5. Top 3% band: small dropped, boundary/large kept.
        views = [View(view_id=0, bbox=(100, 5, 120, 20), area=300, mask_rle=""),
                 View(view_id=1, bbox=(100, 26, 120, 34), area=80, mask_rle=""),
                 View(view_id=2, bbox=(100, 0, 161, 20), area=1220, mask_rle=""),
                 View(view_id=3, bbox=(100, 0, 140, 70), area=2800, mask_rle="")]
        kept = _filter_aux_views(views, OcrResult(), (1000, 1000))
        assert [tuple(v.bbox) for v in kept] == [
            (100, 26, 120, 34), (100, 0, 161, 20), (100, 0, 140, 70)]
        old = _filter_aux_views([views[0]], OcrResult())
        assert [tuple(v.bbox) for v in old] == [(100, 5, 120, 20)]

    print("SELFCHECK OK")


if __name__ == "__main__":
    checks()
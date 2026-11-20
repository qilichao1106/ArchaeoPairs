"""T-011 frozen acceptance: :class:`FileWriter` filesystem sinks.

Covers the card's writer contract on the real filesystem: lossless PNG encode,
Microsoft Windows Chinese paths, UTF-8 ``pairs.jsonl`` / ``ledger.jsonl``
(overwrite semantics and empty-list truncation), and the security rule that a
crafted ``name`` can never escape ``<out_dir>/pairs/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from archaeopairs.output import FileWriter

from t011_synthetic import jsonl_rows


def _sample_image() -> np.ndarray:
    image = np.zeros((6, 8, 3), dtype=np.uint8)
    image[0, 0] = (1, 2, 3)
    image[2, 3] = (40, 50, 60)
    image[-1, -1] = (250, 251, 252)
    return image


def test_write_image_persists_lossless_png_and_returns_relative_path(tmp_path) -> None:
    out = tmp_path / "out"
    writer = FileWriter(out)
    image = _sample_image()

    relative = writer.write_image("图一_1_M4-1.png", image)

    assert relative == "pairs/图一_1_M4-1.png"
    target = out / relative
    assert target.is_file()
    raw = target.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == image.shape
    np.testing.assert_array_equal(decoded, image)


def test_chinese_output_directory_and_utf8_jsonl(tmp_path) -> None:
    out = tmp_path / "中文目录" / "第二册"
    writer = FileWriter(out)
    image = _sample_image()

    relative = writer.write_image("图二_2_陶壶.png", image)
    assert (out / relative).is_file()

    pairs = [
        {"book_id": "考古书", "figure_id": "图二", "artifact_id": "M4:2", "描述": "陶壶"}
    ]
    ledger = [
        {"book_id": "考古书", "figure_id": "图二", "artifact_id": "M4:2", "备注": "中文"}
    ]
    writer.write_pairs(pairs)
    writer.write_ledger(ledger)

    pairs_text = (out / "pairs.jsonl").read_text(encoding="utf-8")
    ledger_text = (out / "ledger.jsonl").read_text(encoding="utf-8")
    assert json.loads(pairs_text) == pairs[0]
    assert json.loads(ledger_text) == ledger[0]
    # ensure_ascii=False: Chinese is stored as UTF-8, not as \uXXXX escapes.
    assert "陶壶" in pairs_text
    assert "\\u9676" not in pairs_text
    assert "中文" in ledger_text


def test_jsonl_sinks_overwrite_and_empty_lists_truncate(tmp_path) -> None:
    out = tmp_path / "out"
    writer = FileWriter(out)

    writer.write_pairs([{"artifact_id": "M4:1"}, {"artifact_id": "M4:2"}])
    writer.write_ledger([{"artifact_id": "M4:1"}])
    assert [row["artifact_id"] for row in jsonl_rows(out / "pairs.jsonl")] == [
        "M4:1",
        "M4:2",
    ]
    assert [row["artifact_id"] for row in jsonl_rows(out / "ledger.jsonl")] == [
        "M4:1"
    ]

    # A re-run replaces the file instead of appending to the previous book.
    writer.write_pairs([{"artifact_id": "M4:9"}])
    pairs_text = (out / "pairs.jsonl").read_text(encoding="utf-8")
    assert jsonl_rows(out / "pairs.jsonl") == [{"artifact_id": "M4:9"}]
    assert pairs_text.endswith("\n")
    assert pairs_text.count("\n") == 1

    # An empty list is not dropped: the sinks exist and are truncated.
    writer.write_pairs([])
    writer.write_ledger([])
    assert (out / "pairs.jsonl").is_file()
    assert (out / "ledger.jsonl").is_file()
    assert (out / "pairs.jsonl").read_text(encoding="utf-8") == ""
    assert (out / "ledger.jsonl").read_text(encoding="utf-8") == ""


def test_write_image_rejects_non_ndarray(tmp_path) -> None:
    writer = FileWriter(tmp_path / "out")

    with pytest.raises(OSError, match="not a numpy array"):
        writer.write_image("bad.png", [[0, 0, 0]])

    assert not (writer.out_dir / "pairs" / "bad.png").exists()


def test_write_image_discards_directory_components(tmp_path) -> None:
    out = tmp_path / "out"
    writer = FileWriter(out)

    crafted_names = ["../../escape.png", r"..\..\escape_win.png"]
    for name in crafted_names:
        expected = Path(name).name
        relative = writer.write_image(name, _sample_image())
        assert relative == (Path("pairs") / expected).as_posix()
        target = (out / relative).resolve()
        assert target.is_file()
        assert target.is_relative_to(out.resolve())

    absolute = str(tmp_path / "absolute.png")
    relative = writer.write_image(absolute, _sample_image())
    assert relative == "pairs/absolute.png"
    assert (out / relative).is_file()

    assert not (tmp_path / "escape.png").exists()
    assert not (tmp_path / "escape_win.png").exists()
    assert not (tmp_path / "absolute.png").exists()


def test_filewriter_rejects_a_file_as_out_dir(tmp_path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")

    with pytest.raises(OSError):
        FileWriter(blocker)


def test_write_image_rejects_empty_name(tmp_path) -> None:
    writer = FileWriter(tmp_path / "out")

    # An empty name resolves to ``<out>/pairs`` itself; writing bytes to a
    # directory must fail loudly rather than silently dropping the image.
    with pytest.raises(OSError):
        writer.write_image("", _sample_image())
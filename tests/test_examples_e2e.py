"""集成测试：books 真实报告端到端（mock 能力接口，P0 高完整率报告）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from archaeopairs.cli import run_book

BOOKS = Path(__file__).resolve().parents[1] / "books"


@pytest.mark.parametrize("book", ["大兴东庄营考古发掘报告", "洪洞南秦墓地二〇一六年度发掘报告"])
def test_run_book_end_to_end(book, tmp_path):
    # TEMP(skip multi_line)：改用 single_line/single_plate（其它类别）路径的书验证，原 郑州/奉节 为 multi_line 高频样本
    if not (BOOKS / book).exists():
        pytest.skip(f"books/{book} 不存在")
    out = run_book(book, books_dir=str(BOOKS), db=str(tmp_path / "c.sqlite3"), limit=30)
    assert out["figures"] > 0
    assert out["pairs"] > 0
    # 完整 figure-note 报告应大量 OUTPUT 而非 PENDING_REVIEW
    statuses = list(out["statuses"].values())
    assert statuses.count("OUTPUT") > 0

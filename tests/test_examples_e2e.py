"""集成测试：books 真实报告端到端（mock 能力接口，P0 高完整率报告）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from archaeopairs.cli import run_book

BOOKS = Path(__file__).resolve().parents[1] / "books"


@pytest.mark.parametrize("book", ["郑州商城", "奉节白帝城（白帝村、白帝山、紫阳城遗址）"])
def test_run_book_end_to_end(book, tmp_path):
    if not (BOOKS / book).exists():
        pytest.skip(f"books/{book} 不存在")
    out = run_book(book, books_dir=str(BOOKS), db=str(tmp_path / "c.sqlite3"), limit=30)
    assert out["figures"] > 0
    assert out["pairs"] > 0
    # 完整 figure-note 报告应大量 OUTPUT 而非 PENDING_REVIEW
    statuses = list(out["statuses"].values())
    assert statuses.count("OUTPUT") > 0

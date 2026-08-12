"""存储层测试：建表对齐 DDL、落库、claim、对象存储安全（§6.5/§9.3/§4.4）。"""
from __future__ import annotations

import pytest

from archaeopairs.errors import E1100StorageError
from archaeopairs.storage import (DiagnosticReportRow, FigureStateRow, PairRecordRow,
                                  LocalObjectStore, claim_figure, make_session_factory)


def test_tables_created(tmp_path):
    sf = make_session_factory(f"sqlite:///{tmp_path}/m.sqlite3")
    with sf() as s:
        s.add(FigureStateRow(book_id="b", figure_id="f", fileref="m/i.jpg"))
        s.flush()
        fs = s.query(FigureStateRow).first()
        s.add(DiagnosticReportRow(figure_state_id=fs.id, iteration=0, report={"x": 1}))
        s.add(PairRecordRow(book_id="b", artifact_id="M4:1", image_path="p.png"))
        s.commit()
    with sf() as s:
        assert s.query(DiagnosticReportRow).count() == 1
        assert s.query(PairRecordRow).count() == 1


def test_claim_figure(tmp_path):
    sf = make_session_factory(f"sqlite:///{tmp_path}/m.sqlite3")
    with sf() as s:
        s.add(FigureStateRow(book_id="b", figure_id="f", fileref="m/i.jpg", status="INIT"))
        s.commit()
    with sf() as s:
        assert claim_figure(s, "b", "f") is True
        s.commit()
    with sf() as s:
        assert claim_figure(s, "b", "f") is False  # 已认领


def test_object_store_path_traversal(tmp_path):
    st = LocalObjectStore(tmp_path / "obj")
    with pytest.raises(E1100StorageError):
        st.put_bytes("../evil.png", b"x")
    assert st.put_bytes("a/b.png", b"x").endswith("b.png")
    assert st.exists("a/b.png")

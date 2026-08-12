"""S3 正文切分测试（§4.3.2 决策树）。"""
from __future__ import annotations

from archaeopairs.parsers import s3_text


def test_single_anchor():
    out = s3_text.split_body([("p1", "M4:1 夹砂灰陶，器形完整。")])
    assert out[0].artifact_id == "M4:1"
    assert out[0].confidence == 0.95


def test_multi_anchor():
    out = s3_text.split_body([("p1", "M4:1 陶豆。M4:2 陶壶。")])
    assert {t.artifact_id for t in out} == {"M4:1", "M4:2"}


def test_no_anchor_attaches_last():
    out = s3_text.split_body([("p1", "M4:1 陶豆。"), ("p2", "1件。口径十厘米。")])
    assert out[1].artifact_id == "M4:1"
    assert "piece_count" in out[1].markers

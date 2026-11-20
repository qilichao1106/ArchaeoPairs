"""T-003 body splitting by artifact anchors (card §3, R-OUT-03).

Frozen expectations:

* one anchor -> whole paragraph belongs to that artifact (``single_anchor``);
* several anchors -> cut at the specimen/sentence boundaries, each artifact
  keeps its own slice (``multi_anchor``);
* no anchor -> hang on the nearest preceding anchor (``no_anchor``); a leading
  no-anchor paragraph has none and is dropped rather than guessed.
"""

from __future__ import annotations

import pytest

from archaeopairs.text.body import split_body


@pytest.mark.parametrize("artifact_id", ["M4:1", "M39:8-1", "00FBH1:6", "2004CWWM11:5"])
def test_single_anchor_keeps_the_whole_paragraph(artifact_id):
    text = f"标本{artifact_id}，陶豆，口径10厘米。盖面饰弦纹。"
    artifacts = split_body([("p1", text)])
    assert len(artifacts) == 1
    assert artifacts[0].artifact_id == artifact_id
    assert artifacts[0].text == text
    assert artifacts[0].source_para_ids == ["p1"]
    assert artifacts[0].markers == ["single_anchor"]


def test_multiple_anchors_are_cut_into_their_own_slices():
    text = "标本M4:1，陶豆，口径10厘米。标本M4:2，陶壶，高8厘米。"
    artifacts = split_body([("p1", text)])
    assert [artifact.artifact_id for artifact in artifacts] == ["M4:1", "M4:2"]
    assert artifacts[0].markers == ["multi_anchor"]
    assert artifacts[1].markers == ["multi_anchor"]
    assert "M4:1" in artifacts[0].text
    assert "陶豆" in artifacts[0].text
    assert "M4:2" not in artifacts[0].text
    assert "陶壶" not in artifacts[0].text
    assert "M4:2" in artifacts[1].text
    assert "陶壶" in artifacts[1].text
    assert "M4:1" not in artifacts[1].text
    assert artifacts[0].source_para_ids == ["p1"]
    assert artifacts[1].source_para_ids == ["p1"]


def test_no_anchor_paragraph_hangs_on_the_previous_anchor():
    artifacts = split_body(
        [
            ("p1", "标本M4:1，陶豆。"),
            ("p2", "该器为泥质灰陶，轮制。"),
        ]
    )
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.artifact_id == "M4:1"
    assert artifact.text == "标本M4:1，陶豆。\n该器为泥质灰陶，轮制。"
    assert artifact.source_para_ids == ["p1", "p2"]
    assert artifact.markers == ["single_anchor", "no_anchor"]


def test_leading_no_anchor_paragraph_is_dropped():
    artifacts = split_body(
        [
            ("p0", "图版说明：此页无器物号。"),
            ("p1", "标本M4:1，陶豆。"),
        ]
    )
    assert [artifact.artifact_id for artifact in artifacts] == ["M4:1"]
    assert artifacts[0].source_para_ids == ["p1"]


def test_dict_paragraphs_are_accepted():
    artifacts = split_body([{"id": "p7", "text": "标本M4:3，铜剑。"}])
    assert len(artifacts) == 1
    assert artifacts[0].artifact_id == "M4:3"
    assert artifacts[0].source_para_ids == ["p7"]
    assert artifacts[0].markers == ["single_anchor"]
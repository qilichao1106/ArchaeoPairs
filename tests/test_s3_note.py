"""S3 图注解析器单元测试（§4.3.1 / §5.6 语法用例）。"""
from __future__ import annotations

from archaeopairs.parsers import s3_note


def test_single():
    items = s3_note.parse_note("1. 骨笄")
    assert items[0].seq_list == [1] and items[0].name == "骨笄"


def test_group_with_artifacts():
    items = s3_note.parse_note("1、2. 陶豆（M4:2、M4:1） 3. 铜剑（M4:3）")
    assert items[0].seq_list == [1, 2]
    assert set(items[0].artifact_ids) == {"M4:2", "M4:1"}
    assert items[1].artifact_ids == ["M4:3"]


def test_range():
    items = s3_note.parse_note("1～4. 豆（M3:4、M3:2、M3:3、M3:1） 5. 壶（M3:5）")
    assert items[0].seq_list == [1, 2, 3, 4]
    assert len(items[0].artifact_ids) == 4


def test_noise_skipped():
    items = s3_note.parse_note("0 8厘米")
    assert items == []


def test_colon_normalize():
    items = s3_note.parse_note("1. 陶罐（M369∶4）")
    assert items[0].artifact_ids == ["M369:4"]


def test_registry_has_rule():
    assert "rule" in list(s3_note.registered())

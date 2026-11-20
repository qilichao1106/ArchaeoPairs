"""Self-check for T-003: figure-note parsing + seq -> artifact mapping.

Run from the project root:

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-003/selfcheck_t003.py

The log ``selfcheck/T-003/selfcheck.log`` is written by this script itself with
``encoding="utf-8"`` (see :class:`_Tee`).  Never redirect this script with
PowerShell ``>``: that writes UTF-16 with a BOM, which round 2 replaced.

Covers the frozen cases from the T-003 fix request (round 3):

1. ``①骨笄（M4:1） ②陶豆（M4:2）`` -> two clauses, seq 1/2, ids M4:1/M4:2;
1b. ``①、②. 陶豆（M4:2、M4:1）`` -> ONE clause, seq ``1、2``;
2. ``1、2. 陶豆（M4:2、M4:1） 3. 铜剑（M4:3）`` -> per-seq keys 1/2/3, ``rule_a``;
3. ``1～4.豆（M3:4、M3:2、M3:3、M3:1）`` -> positional zip, ``range_split``;
4. ``4、6、7. 串珠（M1:29）`` -> rule B, all three keys share M1:29;

plus the caption-fallback / conflict rules:

5. a note with artifacts yields ``caption_artifacts == []``; the caption is
   only used when note clauses carry no artifact ids;
6. a single seq with two artifacts is legal (``split_same_seq``), while one
   artifact claimed by different seqs -> ``conflicts`` and no guessing.
"""

from __future__ import annotations

import sys
from pathlib import Path


class _Tee:
    """Mirror writes to the console and to the UTF-8 selfcheck log."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


# Force UTF-8 output regardless of the console code page (cp936/GBK on
# Windows) so Chinese notes/names never turn into mojibake in the log.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - exotic stream
        pass

LOG_PATH = Path(__file__).resolve().with_name("selfcheck.log")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from archaeopairs.mapping.text_map import build_text_mapping  # noqa: E402
from archaeopairs.text.note import extract_caption_artifacts, parse_note  # noqa: E402


def _map(note: str, caption: str = ""):
    """Parse a note and map it with the caption as the weak fallback."""
    return build_text_mapping(parse_note(note), extract_caption_artifacts(caption), [])


def case1_circled_notes() -> None:
    items = parse_note("①骨笄（M4:1） ②陶豆（M4:2）")
    assert len(items) == 2, [i.model_dump() for i in items]
    assert [i.seq_list for i in items] == [[1], [2]], [i.seq_list for i in items]
    assert [i.artifact_ids for i in items] == [["M4:1"], ["M4:2"]], [
        i.artifact_ids for i in items
    ]
    print("case1 circled      :", [(i.seq, i.name, i.artifact_ids) for i in items])


def case2_grouped_heads() -> None:
    mapping = _map("1、2. 陶豆（M4:2、M4:1） 3. 铜剑（M4:3）")
    assert mapping.seq_to_artifacts == {
        "1": ["M4:2"],
        "2": ["M4:1"],
        "3": ["M4:3"],
    }, mapping.seq_to_artifacts
    # N:N pairs are rule_a: only a range seq (1～4) is range_split.
    assert mapping.case_type == "rule_a", mapping.case_type
    assert mapping.caption_artifacts == [], mapping.caption_artifacts
    assert mapping.conflicts == [], mapping.conflicts
    print("case2 grouped heads:", mapping.seq_to_artifacts, mapping.case_type)


def case1b_circled_group() -> None:
    # A marker whose body is only whitespace/、,，.。 accumulates; the next
    # marker with real text flushes ONE clause with the joined seq.
    items = parse_note("①、②. 陶豆（M4:2、M4:1）")
    assert len(items) == 1, [i.model_dump() for i in items]
    assert items[0].seq == "1、2", items[0].seq
    assert items[0].seq_list == [1, 2], items[0].seq_list
    assert items[0].artifact_ids == ["M4:2", "M4:1"], items[0].artifact_ids
    assert _map("①、②. 陶豆（M4:2、M4:1）").seq_to_artifacts == {
        "1": ["M4:2"],
        "2": ["M4:1"],
    }
    print("case1b circled grp :", items[0].seq, items[0].artifact_ids)


def case3_range_split() -> None:
    mapping = _map("1～4.豆（M3:4、M3:2、M3:3、M3:1）")
    assert mapping.seq_to_artifacts == {
        "1": ["M3:4"],
        "2": ["M3:2"],
        "3": ["M3:3"],
        "4": ["M3:1"],
    }, mapping.seq_to_artifacts
    assert mapping.case_type == "range_split", mapping.case_type
    assert mapping.caption_artifacts == [], mapping.caption_artifacts
    print("case3 range split  :", mapping.seq_to_artifacts, mapping.case_type)


def case4_rule_b() -> None:
    mapping = _map("4、6、7. 串珠（M1:29）")
    assert mapping.seq_to_artifacts == {
        "4": ["M1:29"],
        "6": ["M1:29"],
        "7": ["M1:29"],
    }, mapping.seq_to_artifacts
    assert mapping.case_type == "rule_b", mapping.case_type
    assert mapping.caption_artifacts == [], mapping.caption_artifacts
    assert mapping.conflicts == [], mapping.conflicts
    print("case4 rule B       :", mapping.seq_to_artifacts, mapping.case_type)


def case5_caption_fallback() -> None:
    # Note has ids: caption (M9:9) must not leak in.
    with_ids = _map("①骨笄（M4:1） ②陶豆（M4:2）", "图一 骨笄（M9:9）")
    assert with_ids.caption_artifacts == [], with_ids.caption_artifacts
    assert "M9:9" not in {aid for ids in with_ids.seq_to_artifacts.values() for aid in ids}
    # Note has seqs but no ids: caption title is the only source.
    fallback = _map("1. 陶豆 2. 陶壶", "图五 陶豆（M4:1、M4:2）")
    assert fallback.seq_to_artifacts == {"1": ["M4:1"], "2": ["M4:2"]}, (
        fallback.seq_to_artifacts
    )
    assert fallback.caption_artifacts == [], fallback.caption_artifacts
    print("case5 caption      :", with_ids.caption_artifacts, fallback.seq_to_artifacts)


def case6_conflicts() -> None:
    # 1 seq : 2 art is LEGAL: every artifact hangs on that single seq.
    split = _map("1. 陶豆（M4:1、M4:2）")
    assert split.seq_to_artifacts == {"1": ["M4:1", "M4:2"]}, split.seq_to_artifacts
    assert split.case_type == "split_same_seq", split.case_type
    assert not any(
        c.startswith("cardinality_mismatch:") for c in split.conflicts
    ), split.conflicts
    assert split.conflicts == [], split.conflicts
    # Same artifact declared by unrelated seqs -> conflict, mapping kept.
    repeated = _map("1. 陶豆（M4:1、M4:2） 2. 陶壶（M4:2）")
    assert repeated.seq_to_artifacts == {"1": ["M4:1", "M4:2"], "2": ["M4:2"]}, (
        repeated.seq_to_artifacts
    )
    assert any(
        c.startswith("artifact_claimed_by_multiple_seqs:M4:2:") for c in repeated.conflicts
    ), repeated.conflicts
    print(
        "case6 conflicts    :",
        split.seq_to_artifacts,
        split.case_type,
        repeated.conflicts,
    )


def main() -> int:
    log = open(LOG_PATH, "w", encoding="utf-8", newline="\n")
    console = sys.stdout
    sys.stdout = _Tee(console, log)
    try:
        return _run_cases()
    finally:
        log.flush()
        log.close()
        sys.stdout = console


def _run_cases() -> int:
    case1_circled_notes()
    case1b_circled_group()
    case2_grouped_heads()
    case3_range_split()
    case4_rule_b()
    case5_caption_fallback()
    case6_conflicts()
    print("SELFCHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
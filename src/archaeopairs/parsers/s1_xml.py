"""S1 报告索引器（对齐《技术方案 V0.4》报告索引器（§4.1）/ XML 结构（§2.1）上游输入契约）。

解析 DocBook data.xml：关联 figure 与 figure-title/figure-note，产出
FigureRecord 列表与 ground（供 mock 能力接口），并做摄入期契约校验。

figure ↔ figure-note 关联（修复 P0-1）：
  * 组后紧邻图注多段合并；
  * 图注前置回溯（跳过 figure-title 段落）；
  * 同图号连续 figure 分组，图注归属组内最大面积的 figure；
  * 无 caption 的 figure 可从紧邻前置 para role="figure-title" 恢复图题；
  * 契约违约（caption 缺失/无 imagedata）记入 violations（含 fileref 与原因），
    不再静默丢弃——figure 保留进输出，由 S1 节点按 E102 排除并可见。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..state import FigureState
from . import s3_note
from .image_classify import classify_image_type


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _strip_ns(root: ET.Element) -> None:
    # 命名空间无关：剥离 DocBook 命名空间（部分报告带 ns，部分不带）
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _caption_of(fig: ET.Element) -> str | None:
    cap = fig.find(".//caption[@role='figure-title']")
    return _text(cap) if cap is not None else None


def _area_of(fig: ET.Element) -> int:
    im = fig.find(".//imagedata")
    if im is None:
        return 0
    try:
        return int(im.get("contentwidth") or 0) * int(im.get("contentdepth") or 0)
    except ValueError:
        return 0


def parse_report(xml_path: str | Path, book_id: str) -> tuple[list[FigureState], dict, list[str]]:
    """返回 (figures, ground, violations)。violations 格式：figure_id|fileref|原因。"""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    _strip_ns(root)
    figures: list[FigureState] = []
    ground: dict[str, dict] = {}
    violations: list[str] = []

    for parent in root.iter():
        children = list(parent)
        consumed: set[int] = set()  # 已归属的 figure-note para 下标
        n = len(children)
        i = 0
        while i < n:
            if children[i].tag != "figure":
                i += 1
                continue

            # 1) 同图号连续 figure 分组（caption 均非空且相等才成组）
            cap_i = _caption_of(children[i])
            group = [i]
            j = i + 1
            while j < n and children[j].tag == "figure":
                cap_j = _caption_of(children[j])
                if cap_i and cap_j and cap_i == cap_j:
                    group.append(j)
                    j += 1
                else:
                    break

            # 2) 组后紧邻 figure-note 多段收集
            forward_notes: list[str] = []
            k = j
            while k < n:
                nxt = children[k]
                if nxt.tag == "para" and nxt.get("role") == "figure-note":
                    forward_notes.append(_text(nxt))
                    consumed.add(k)
                    k += 1
                else:
                    break

            # 3) 每个成员向前回溯：紧邻图注（未消费）+ 相邻图题恢复
            pre_notes: dict[int, list[str]] = {}
            pre_title: dict[int, str | None] = {}
            for pos in group:
                pre = pos - 1
                notes_before: list[str] = []
                title_before: str | None = None
                steps = 0
                while pre >= 0 and steps < 4:
                    el = children[pre]
                    if el.tag == "para":
                        role = el.get("role")
                        if role == "figure-note":
                            if pre not in consumed:
                                notes_before.insert(0, _text(el))
                                consumed.add(pre)
                            pre -= 1
                            steps += 1
                            continue
                        if role == "figure-title":
                            if title_before is None:
                                title_before = _text(el)
                            pre -= 1
                            steps += 1
                            continue
                    break
                pre_notes[pos] = notes_before
                pre_title[pos] = title_before

            # 4) 组内图注归属：面积最大的 figure（组合图本体，条状比例尺图不取）
            primary = max(group, key=lambda pos: _area_of(children[pos]))

            # 5) 产出 FigureState 与 ground
            for pos in group:
                fig_el = children[pos]
                im = fig_el.find(".//imagedata")
                fileref = im.get("fileref", "") if im is not None else ""
                fid = f"{book_id}:{Path(fileref).stem}" if fileref else f"{book_id}:fig_{len(figures)}"
                if im is None:
                    violations.append(f"{fid}|{fileref}|media_missing")
                    continue
                caption = _caption_of(fig_el)
                if caption is None:
                    caption = pre_title[pos]
                if caption is None:
                    violations.append(f"{fid}|{fileref}|caption_missing")
                note_text = "\n".join(pre_notes[pos] + (forward_notes if pos == primary else []))
                figures.append(FigureState(
                    book_id=book_id, figure_id=fid, fileref=fileref,
                    caption=caption, figure_note=note_text or None, status="INIT",
                ))
                # ground：供 mock 能力接口。与 S2 运行时同口径——image_type 传入与运行时
                # 相同的 image_path(xml.parent/fileref) 做像素家族判定（缺图自动回退关键词）。
                image_path = Path(xml_path).parent / fileref if fileref else None
                items = s3_note.parse_note(note_text)
                seqs: list[str] = []
                for it in items:
                    seqs.extend(str(s) for s in it.seq_list)
                    if not it.seq_list and it.seq:
                        seqs.append(str(it.seq))
                arts = [a for it in items for a in it.artifact_ids]
                if not arts:
                    arts = s3_note.extract_caption_artifacts(caption)
                ground[fid] = {
                    "seqs": seqs,
                    "artifact_ids": arts,
                    "image_type": classify_image_type(caption, note_text, image_path),
                }
            # 跳过组内已消费的图注段落
            i = max(j, k)
    return figures, ground, violations


_SKIP_ROLES = {"figure-note", "figure-title", "table-title", "qr-caption"}


def parse_body(xml_path: str | Path) -> list[dict]:
    """提取正文段落（链②语料），供 S3 正文切分。

    排除 figure-note/figure-title/table-title/qr-caption 角色，
    避免图题与表格标题污染链②正文。
    """
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    _strip_ns(root)
    out: list[dict] = []
    for i, p in enumerate(root.iter("para")):
        if p.get("role") in _SKIP_ROLES:
            continue
        text = "".join(p.itertext()).strip()
        if text:
            out.append({"id": f"p{i}", "text": text})
    return out

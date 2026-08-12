"""S1 报告索引器（对齐《技术方案 V0.1》§4.1 / §2.1 上游输入契约）。

解析 DocBook data.xml：关联 figure 与 figure-title/figure-note，产出
FigureRecord 列表与 ground（供 mock 能力接口），并做摄入期契约校验
（caption 无 role / figure-title 缺失 → E102 违约清单，不本地回退）。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..state import FigureState
from . import s3_note

_PLATE_RE = re.compile(r"图版|圖版")
_PLATE_SCENE_RE = re.compile(r"墓葬|室墓|夯土|发掘|场景|隔梁|地层|遗迹")
_DISCARD_RE = re.compile(r"平面|剖面|墓室|地层|遗迹|区位|位置示意")


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_report(xml_path: str | Path, book_id: str) -> tuple[list[FigureState], dict, list[str]]:
    """返回 (figures, ground, violations)。"""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    # 命名空间无关：剥离 DocBook 命名空间（部分报告带 ns，部分不带）
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    figures: list[FigureState] = []
    ground: dict[str, dict] = {}
    violations: list[str] = []

    # 建立 figure -> 后续 figure-note 映射（兄弟 para）
    for parent in root.iter():
        children = list(parent)
        for i, child in enumerate(children):
            if child.tag != "figure":
                continue
            cap = child.find(".//caption[@role='figure-title']")
            im = child.find(".//imagedata")
            if cap is None or im is None:
                fid = f"{book_id}:fig_{len(figures)}"
                violations.append(fid)  # 契约违约（E102）
                continue
            caption = _text(cap)
            fileref = im.get("fileref", "")
            # 其后紧邻 figure-note
            note_text = ""
            for nxt in children[i + 1:]:
                if nxt.tag == "figure":
                    break
                if nxt.tag == "para" and nxt.get("role") == "figure-note":
                    note_text = _text(nxt)
                    break
            fid = f"{book_id}:{Path(fileref).stem}"
            figures.append(FigureState(
                book_id=book_id, figure_id=fid, fileref=fileref,
                caption=caption, figure_note=note_text or None, status="INIT",
            ))
            # ground：供 mock 能力接口
            items = s3_note.parse_note(note_text)
            seqs: list[str] = []
            for it in items:
                seqs.extend(str(s) for s in it.seq_list)
                if not it.seq_list and it.seq:
                    seqs.append(str(it.seq))
            arts = [a for it in items for a in it.artifact_ids]
            if _PLATE_RE.search(caption):
                itype = "plate_scene" if _PLATE_SCENE_RE.search(caption) else "plate_artifact"
            elif _DISCARD_RE.search(caption) and not items:
                itype = "discarded"
            else:
                itype = "line_drawing"
            ground[fid] = {"seqs": seqs, "artifact_ids": arts, "image_type": itype}
    return figures, ground, violations


def parse_body(xml_path: str | Path) -> list[dict]:
    """提取正文段落（链②语料），供 S3 正文切分。"""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    out: list[dict] = []
    for i, p in enumerate(root.iter("para")):
        if p.get("role") == "figure-note":
            continue
        text = "".join(p.itertext()).strip()
        if text:
            out.append({"id": f"p{i}", "text": text})
    return out

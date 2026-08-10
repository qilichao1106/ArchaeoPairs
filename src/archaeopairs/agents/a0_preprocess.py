# -*- coding: utf-8 -*-
"""A0 预处理索引：DocBook 解析、figure/图版索引、schema 校验、图题先验分流预计算。

分两层：
- BookIndexer.parse_book()：报告级一次性解析（figures + body_paras + figure-note 关联）；
- A0Preprocess（Agent）：figure 级校验与 figure_index 落 state。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..agent import AgentInterface, AgentContext
from ..errors import AgentError, ErrorCode, ReviewRequired
from ..regexes import normalize_figure_no, caption_mode
from ..state import PairState

NS = "{http://docbook.org/ns/docbook}"


def _localname(tag: str) -> str:
    return tag.split("}", 1)[-1]          # ns 容错：忽略命名空间前缀差异


@dataclass
class FigureRecord:
    figure_id: str
    fileref: str
    caption: str = ""
    figure_no_norm: str = ""
    figure_no_original: str = ""
    note_text: str = ""                   # 紧邻的 figure-note（链①）
    page: str = ""
    caption_mode: str = "uncertain"
    case_pred: str = "case2"              # 底部文字带检测前默认情形二
    media_exists: bool = False


@dataclass
class BodyPara:
    text: str
    page: str = ""


@dataclass
class BookIndex:
    book_id: str
    figures: list[FigureRecord] = field(default_factory=list)
    body_paras: list[BodyPara] = field(default_factory=list)
    element_hist: dict = field(default_factory=dict)   # schema 漂移探测基线


class BookIndexer:
    """报告级解析器。遍历文档序，将 figure 与其后紧邻的 <para role="figure-note"> 关联。"""

    def __init__(self, xml_path: str, media_dir: str, book_id: str):
        self.xml_path = Path(xml_path)
        self.media_dir = Path(media_dir)
        self.book_id = book_id

    def parse(self) -> BookIndex:
        try:
            tree = ET.parse(self.xml_path)
        except ET.ParseError as e:
            raise AgentError(ErrorCode.E_XML_INVALID, f"XML 解析失败: {e}", fatal=True)
        root = tree.getroot()
        idx = BookIndex(book_id=self.book_id)
        hist: dict[str, int] = {}
        for el in root.iter():
            hist[_localname(el.tag)] = hist.get(_localname(el.tag), 0) + 1
        idx.element_hist = hist
        # schema 漂移探测：与基线元素直方图比对（缺失核心元素即告警）
        for must in ("figure", "imagedata", "para", "caption"):
            if hist.get(must, 0) == 0:
                raise AgentError(ErrorCode.E_XML_INVALID,
                                 f"schema 漂移：缺少核心元素 <{must}>", fatal=True)

        fig_no = 0
        # 文档序遍历：figure 出现后记 pending，下一个 figure-note para 归它
        pending: FigureRecord | None = None
        for el in root.iter():
            name = _localname(el.tag)
            if name == "figure":
                fig_no += 1
                pending = self._parse_figure(el, fig_no)
                idx.figures.append(pending)
            elif name == "para":
                role = el.get("role", "")
                text = "".join(el.itertext()).strip()
                if role == "figure-note" and pending is not None and not pending.note_text:
                    pending.note_text = text
                    pending = None
                elif role not in ("figure-title",):
                    idx.body_paras.append(BodyPara(text=text, page=el.get("page", "")))
        return idx

    def _parse_figure(self, el: ET.Element, seq: int) -> FigureRecord:
        fileref = ""
        caption = ""
        for sub in el.iter():
            nm = _localname(sub.tag)
            if nm == "imagedata" and not fileref:
                fileref = sub.get("fileref", "")
            elif nm == "caption" and sub.get("role") == "figure-title":
                caption = "".join(sub.itertext()).strip()
        norm, original = normalize_figure_no(caption)
        # fileref 形如 "media/image4.jpg"：相对书根目录；media_dir 已指向 media/ 时取文件名
        media_path = self.media_dir / fileref
        if not media_path.exists():
            media_path = self.media_dir / Path(fileref).name
        return FigureRecord(
            figure_id=f"fig-{seq:04d}",
            fileref=fileref,
            caption=caption,
            figure_no_norm=norm,
            figure_no_original=original,
            caption_mode=caption_mode(caption),
            media_exists=bool(fileref) and media_path.exists(),
        )


class A0Preprocess(AgentInterface):
    name = "A0"
    timeout_s = 10
    output_fields = ["figure_index"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        rec: FigureRecord = ctx.config["__figure__"]      # 编排层注入当前 figure 记录
        if not rec.fileref:
            raise AgentError(ErrorCode.E_XML_INVALID,
                             f"{rec.figure_id} 缺 imagedata fileref", fatal=True)
        if not rec.media_exists:
            raise ReviewRequired(ErrorCode.E_FILE_MISSING, "text",
                                 rec.fileref, f"图像文件缺失: {rec.fileref}")
        state.figure_index = {
            "figure_id": rec.figure_id, "fileref": rec.fileref,
            "figure_no": {"norm": rec.figure_no_norm, "original": rec.figure_no_original},
            "caption": rec.caption, "note_text": rec.note_text,
            "case_pred": rec.case_pred, "caption_mode": rec.caption_mode,
            "page": rec.page,
        }
        self.emit(state, "*", "figure_index")
        return state

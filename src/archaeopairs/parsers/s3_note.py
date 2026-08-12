"""S3 图注解析器（对齐《技术方案 V0.1》§4.3.1 / O6 NoteParser 策略接口）。

图注语法用例注册为独立 parser，新增用例通过注册扩展，不改动主流程。
默认注册规则解析器，覆盖 §5.6 主要语法形态。
"""
from __future__ import annotations

import re
from typing import Callable, Iterable

from ..state import NoteItem

# ---- 归一化（§2.2.1） ----
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def normalize(text: str) -> str:
    text = text.replace("∶", ":").replace("：", ":")  # 冒号统一
    for i, ch in enumerate(_CIRCLED, start=1):         # 圈号归一
        text = text.replace(ch, str(i))
    return text


# 器物号：M4:6 / 2004CWWM11:5 / C5.1H146:1 / H83:35；部件号 Bb9/Zhb2
ARTIFACT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*:\d+(?:-\d+)?")
COMPONENT_RE = re.compile(r"\b[A-Z][a-z]\d+\b")

_HEAD_RE = re.compile(r"(?P<seq>\d+(?:\s*[～~]\s*\d+)?(?:\s*[、,]\s*\d+)*|[A-Z])\s*[.、]?")

# 纯比例尺噪声
_NOISE_RE = re.compile(r"^[\d\s\-.～~]*厘米?$")


def _expand_seq(raw: str) -> list[int]:
    raw = raw.replace("～", "~").replace("，", ",").replace("、", ",").strip()
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "~" in part:
            a, b = part.split("~", 1)
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def parse_note_rule(text: str) -> list[NoteItem]:
    """规则解析器：屏蔽器物号区间后定位序号头，再在相邻头之间提取名称/器物号。"""
    if not text:
        return []
    text = normalize(text)
    art_spans = [m.span() for m in ARTIFACT_RE.finditer(text)]
    art_spans += [m.span() for m in COMPONENT_RE.finditer(text)]

    def _in_art(span: tuple[int, int]) -> bool:
        return any(s <= span[0] < e for s, e in art_spans)

    heads = [m for m in _HEAD_RE.finditer(text) if not _in_art(m.span("seq"))]
    items: list[NoteItem] = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        seg = text[start:end].strip()
        arts = ARTIFACT_RE.findall(seg) or COMPONENT_RE.findall(seg)
        name = seg.split("（")[0].split("(")[0].strip()
        if not arts and _NOISE_RE.match(seg):
            continue  # 纯比例尺噪声
        if not name and not arts:
            continue
        items.append(NoteItem(seq=m.group("seq").strip(), seq_list=_expand_seq(m.group("seq")),
                              name=name or None, artifact_ids=arts))
    return items


# ---- 策略注册表（O6） ----
_REGISTRY: dict[str, Callable[[str], list[NoteItem]]] = {}


def register(name: str) -> Callable[[Callable[[str], list[NoteItem]]], Callable[[str], list[NoteItem]]]:
    def deco(fn: Callable[[str], list[NoteItem]]) -> Callable[[str], list[NoteItem]]:
        _REGISTRY[name] = fn
        return fn
    return deco


register("rule")(parse_note_rule)


def parse_note(text: str, strategy: str = "rule") -> list[NoteItem]:
    return _REGISTRY[strategy](text)


def registered() -> Iterable[str]:
    return _REGISTRY.keys()

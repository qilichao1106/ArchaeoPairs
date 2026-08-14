"""S3 图注解析器（对齐《技术方案 V0.2》§4.3.1 / O6 NoteParser 策略接口）。

图注语法用例注册为独立 parser，新增用例通过注册扩展，不改动主流程。
默认注册规则解析器，覆盖 §5.6 主要语法形态。

归一化（§2.2.1）全部为 1:1 字符替换（保证归一化文本与原文的 span 可回映）：
冒号统一、圈号→数字（仅用于匹配，artifact_id 回映原文保留圈号）、全角波浪线→半角、
LaTeX 公式残迹（\\sim/$）等宽替换。
"""
from __future__ import annotations

import re
from typing import Callable, Iterable

from ..state import NoteItem

# ---- 归一化（§2.2.1，1:1 替换保持 span 对齐） ----
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def normalize(text: str) -> str:
    text = text.replace("∶", ":").replace("：", ":")  # 冒号统一
    text = text.replace("～", "~").replace("〜", "~")  # 区间号全角波浪线
    text = text.replace("（", "(").replace("）", ")")  # 全角括号半角化
    text = text.replace("\\sim", "~  ").replace("$", " ")  # LaTeX 公式残迹（等宽）
    for i, ch in enumerate(_CIRCLED, start=1):         # 圈号归一（匹配用）
        text = text.replace(ch, str(i))
    return text


def colon_norm(text: str) -> str:
    """器物号/键值统一：冒号（:：∶）归一为半角（圈号等其余字符保留原文）。"""
    return text.replace("∶", ":").replace("：", ":")


# 器物号：M4:6 / 2004CWWM11:5 / C5.1H146:1 / H83:35；部件号 Bb9/Zhb2
ARTIFACT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*:\d+(?:-\d+)?")
COMPONENT_RE = re.compile(r"\b[A-Z][a-z]\d+\b")

_HEAD_RE = re.compile(r"(?P<seq>\d+(?:\s*[～~]\s*\d+)?(?:\s*[、,]\s*\d+)*|[A-Z])\s*[.、]?")

# 纯比例尺噪声
_NOISE_RE = re.compile(r"^[\d\s\-.～~]*厘米?$")

# 无空格紧贴形态："1.00FBG1:2" 中的 "1." 是序号而非器物号前缀
_LEAD_SEQ_RE = re.compile(r"^\d+\.(?=[A-Za-z0-9.\-]*[A-Za-z][A-Za-z0-9.\-]*:)")


def _expand_seq(raw: str) -> list[int]:
    raw = raw.replace("～", "~").replace("，", ",").replace("、", ",").strip()
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "~" in part:
            a, b = part.split("~", 1)
            a, b = a.strip(), b.strip()
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _strip_leading_seq(norm: str, ms: int, me: int) -> tuple[int, int]:
    """剥离被器物号正则吞掉的图内序号前缀（"1.00FBG1:2" 的 "1."）。"""
    frag = norm[ms:me]
    m = _LEAD_SEQ_RE.match(frag)
    if m and ":" in frag:
        return ms + m.end(), me
    return ms, me


def parse_note_rule(text: str) -> list[NoteItem]:
    """规则解析器：屏蔽器物号区间后定位序号头，再在相邻头之间提取名称/器物号。

    artifact_id 从原文回映（span 1:1），保留圈号等原始字符；仅匹配在归一化文本上进行。
    """
    if not text:
        return []
    norm = normalize(text)
    art_spans: list[tuple[int, int]] = []
    for m in ARTIFACT_RE.finditer(norm):
        art_spans.append(_strip_leading_seq(norm, m.start(), m.end()))
    art_spans += [(m.start(), m.end()) for m in COMPONENT_RE.finditer(norm)]
    art_spans.sort()

    def _in_art(span: tuple[int, int]) -> bool:
        return any(s <= span[0] < e for s, e in art_spans)

    heads = [m for m in _HEAD_RE.finditer(norm) if not _in_art(m.span("seq"))]
    items: list[NoteItem] = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(norm)
        seg = norm[start:end].strip()
        # artifact_id 回映原文（冒号归一、圈号保留原文）
        arts = [colon_norm(text[ms:me]) for ms, me in art_spans if start <= ms and me <= end]
        if not arts and _NOISE_RE.match(seg):
            continue  # 纯比例尺噪声
        name = text[start:end].strip().split("（")[0].split("(")[0].strip(" .、")
        if name in arts:
            name = ""  # 名称实为器物号（无空格紧贴形态）
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

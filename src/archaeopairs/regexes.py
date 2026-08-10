# -*- coding: utf-8 -*-
"""考古编号正则与归一化（方案 §2.4/§2.5，附录C B1–B3 修复已落实）。

修复说明（相对 config/regexes.yaml V0.1 契约的偏差，编码以本模块为准）：
- B1: artifact_id 允许数字开头（00FBG1:2 在基准样本出现 1167 处，为主导形态）。
- B2: 归一化器物号允许子编号多段连字符（00FBH1:5-2 → 00FBH1-5-2）。
- B3: 圈号 transliteration 映射表内置；same_id 正则支持两个及以上序号。

注意：config/regexes.yaml 尚未同步（评审决议本轮不改契约文件），
落地时将本模块正则回写契约文件并保持单测一致。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 圈号映射（B3）
CIRCLE_MAP = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
              "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10"}
CIRCLE_RE = re.compile("[" + "".join(CIRCLE_MAP) + "]")

# ---------------------------------------------------------------- 器物号（B1/B2）
# 单位前缀：数字开头（00FBG1 / 05FBCQ1②）或字母开头（M4 / FBH1），冒号全半角均可；
# 序号部分允许子编号（5-2）。
ARTIFACT_ID_RE = re.compile(
    r"(\d{2}[A-Za-z]{1,3}[A-Za-z0-9①-⑩]*|[A-Za-z]{1,3}[A-Za-z0-9①-⑩]*)"
    r"[:：]"
    r"(\d+(?:-\d+)?)"
)
# 归一化后的合法形态（schema 校验同口径）：前缀-序号(-子编号)
ARTIFACT_ID_NORM_RE = re.compile(r"^[A-Z0-9]+(-[0-9]+)+$")


def normalize_artifact_id(raw: str) -> tuple[str, str]:
    """器物号归一化：圈号→ASCII、全角冒号→半角、冒号→连字符。

    返回 (norm, original)。original 永远保留原始写法用于溯源。
    示例：00FBF1：1 → 00FBF1-1；00FBH1:5-2 → 00FBH1-5-2；05FBCQ1②:8 → 05FBCQ12-8。
    """
    original = raw.strip()
    s = CIRCLE_RE.sub(lambda m: CIRCLE_MAP[m.group()], original)
    s = s.replace("：", ":")
    # 仅把"单位前缀:序号"的分隔冒号替换为连字符（子编号中的 - 保留）
    m = ARTIFACT_ID_RE.search(s)
    if not m:
        return s, original
    norm = f"{m.group(1).upper()}-{m.group(2)}"
    return norm, original


# ---------------------------------------------------------------- 图内序号
SEQ_DOT_RE = re.compile(r"^(\d{1,2})[.．]")
# same_id：两个及以上序号（B3 修复：支持 2、9、11.）
SEQ_SAME_ID_RE = re.compile(r"^(\d{1,2}(?:[、,]\s*\d{1,2})+)[.．]?\s*")
# range：2～5.
SEQ_RANGE_RE = re.compile(r"^(\d{1,2})\s*[~～-]\s*(\d{1,2})[.．]?\s*")

# ---------------------------------------------------------------- 正文引用
FIGURE_REF_RE = re.compile(r"[（(]图([^，,；;)）]+)[，,]\s*(\d+)[)）]")
PLATE_REF_RE = re.compile(r"[（(]图版([^，,；;)）]+)[，,]\s*(\d+)[)）]")

# ---------------------------------------------------------------- 图号归一
_CN_DIGIT = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
FIGURE_NO_RE = re.compile(r"^(图[0-9A-Za-z一二三四五六七八九十百〇]+(?:-\d+)*[a-z]?)")


def _cn2num(s: str) -> int | None:
    """中文数字→阿拉伯。纯数字序列逐位拼接（一六→16、一〇〇→100）；
    含十/百时按算术解析（十六→16、一百二→120）。无法解析返回 None。"""
    if not s:
        return None
    if all(c in _CN_DIGIT for c in s):
        return int("".join(str(_CN_DIGIT[c]) for c in s))
    # 算术解析（仅支持 十/百 量级，覆盖实测样本）
    total, section = 0, 0
    for c in s:
        if c in _CN_DIGIT:
            section = _CN_DIGIT[c]
        elif c == "十":
            total += (section or 1) * 10
            section = 0
        elif c == "百":
            total += (section or 1) * 100
            section = 0
        else:
            return None
    return total + section


def normalize_figure_no(caption: str) -> tuple[str, str]:
    """从图题提取图号并归一：剔除描述性内容，保留字母/数字子编号后缀。

    返回 (norm, original)。示例：
    "图2-1-16 M4出土铜鼎" → (图2-1-16, 图2-1-16)；"图一〇〇 …" → (图100, 图一〇〇)；
    "图七a …" → (图7a, 图七a)。
    """
    m = FIGURE_NO_RE.match(caption.strip())
    if not m:
        return caption.strip(), caption.strip()
    original = m.group(1)
    body = original[1:]
    # 分离后缀：字母子编号（图七a）与连字符数字段（图2-1-16b）
    suffix_m = re.search(r"([a-z])$", body)
    suffix = suffix_m.group(1) if suffix_m else ""
    core = body[:-1] if suffix else body
    if "-" in core:  # 图2-1-16 形式：各段独立归一
        parts = [str(_cn2num(p)) if _cn2num(p) is not None else p
                 for p in core.split("-")]
        norm_core = "-".join(parts)
    else:
        num = _cn2num(core)
        norm_core = str(num) if num is not None else core
    return f"图{norm_core}{suffix}", original


# ---------------------------------------------------------------- 图题先验分流（§2.4）
CAPTION_KW = {
    "artifact": ["出土遗物", "遗物", "纹饰", "器物", "铜", "瓷", "陶", "铁", "玉"],
    "non": ["平剖面图", "平面图", "剖面图", "地层", "遗迹", "墓室", "探方",
            "区位图", "示意图", "分布图"],
    "plate": ["图版"],
}


def caption_mode(caption: str) -> str:
    """图题关键词先验分流：plate > non > artifact > uncertain。

    注意（规范V 特别说明）：图题含"地层"但画面为清晰器物线图时强制 type_a，
    该纠正不在本函数完成，由 A2 的 force_rule_a 流程负责。
    """
    if any(k in caption for k in CAPTION_KW["plate"]):
        return "plate"
    if any(k in caption for k in CAPTION_KW["non"]):
        return "non"
    if any(k in caption for k in CAPTION_KW["artifact"]):
        return "artifact"
    return "uncertain"


# ---------------------------------------------------------------- 图注四形态解析（§2.3）
@dataclass
class NoteEntry:
    """一条图注条目：seqs 为图内序号列表（同号式多 seq），ids 为归一化器物号列表。"""
    seqs: list[str]
    ids: list[str]
    name: str = ""
    form: str = ""                # compact / fullwidth / range / same_id / desc
    raw: str = ""


@dataclass
class NoteParseResult:
    entries: list[NoteEntry] = field(default_factory=list)
    scales: list[str] = field(default_factory=list)   # 比例尺文本（如 0-6厘米）
    residuals: list[str] = field(default_factory=list)  # 未匹配残差（触发降级/LLM）
    note_type: str = "note"       # note / scale / desc

_SCALE_RE = re.compile(r"(\d+)\s*[-—~～]\s*(\d+)\s*(厘米|cm|毫米|mm)", re.I)


def _extract_ids(text: str) -> list[str]:
    return [normalize_artifact_id(m.group(0))[0] for m in ARTIFACT_ID_RE.finditer(text)]


def _strip_name(text: str) -> str:
    """去掉条目中的器物号与括号，留下器物名（如 '铁器（00FBH1：6）' → '铁器'）。"""
    s = ARTIFACT_ID_RE.sub("", text)
    return s.strip("（）() 　、，,")


def parse_figure_note(note_text: str) -> NoteParseResult:
    """解析 figure-note 全文为 seq→ids 条目集合。

    思路：按行/分句切分后逐条识别四形态；范围式按位置序展开 seq 与 id 一一对应；
    同号式拆多个 seq 共享/对应 ids；无法识别的行计入 residuals（由 A1a 决策树
    决定 LLM 二次解析或 degraded）。比例尺行单独抽出。
    """
    result = NoteParseResult()
    text = (note_text or "").strip()
    if not text:
        result.note_type = "desc"
        return result

    # 先抽比例尺（可能单独成行，也可能嵌在条目尾部）
    for m in _SCALE_RE.finditer(text):
        result.scales.append(m.group(0))

    # 按换行切分；单行内可能存在多个 "N." 条目（紧凑式连排），再按序号锚点二次切分
    lines = [ln.strip() for ln in re.split(r"[\n；;]", text) if ln.strip()]
    chunks: list[str] = []
    for ln in lines:
        # 在 "数字+点" 锚点前切分（保留锚点），兼容紧凑式 "1.00FBG1:2 2.00FBG1:1"；
        # 前字符为 顿号/逗号/范围符 时不切（保护同号式 2、9. 与范围式 2～5.）
        parts = re.split(r"(?<![、,，~～\-0-9])(?=\b\d{1,2}[.．])", ln)
        chunks.extend(p.strip() for p in parts if p.strip())

    for chunk in chunks:
        entry = _parse_note_chunk(chunk)
        if entry is None:
            # 纯比例尺行不计残差
            if not _SCALE_RE.fullmatch(chunk.replace(" ", "")):
                result.residuals.append(chunk)
            continue
        result.entries.append(entry)

    if not result.entries and not result.residuals:
        result.note_type = "desc"
    return result


def _parse_note_chunk(chunk: str) -> NoteEntry | None:
    # 范围式：2～5.筒瓦(03FBSL1：1、…)
    m = SEQ_RANGE_RE.match(chunk)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        seqs = [str(i) for i in range(a, b + 1)]
        rest = chunk[m.end():]
        ids = _extract_ids(rest)
        return NoteEntry(seqs=seqs, ids=ids, name=_strip_name(rest),
                         form="range", raw=chunk)
    # 同号式：2、9.铁器（00FBH1：6、00FBH1：3）
    m = SEQ_SAME_ID_RE.match(chunk)
    if m:
        seqs = [s.strip() for s in re.split(r"[、,]", m.group(1))]
        rest = chunk[m.end():]
        ids = _extract_ids(rest)
        return NoteEntry(seqs=seqs, ids=ids, name=_strip_name(rest),
                         form="same_id", raw=chunk)
    # 单序号（紧凑式/全角式统一处理）
    m = SEQ_DOT_RE.match(chunk)
    if m:
        rest = chunk[m.end():]
        ids = _extract_ids(rest)
        form = "compact" if ids and _strip_name(rest) == "" else "fullwidth"
        return NoteEntry(seqs=[m.group(1)], ids=ids, name=_strip_name(rest),
                         form=form, raw=chunk)
    return None

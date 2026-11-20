"""Figure-note parsing and caption fallback (R-SEQ-01, R-MAP-01).

``parse_note`` turns one figure-note string into ordered :class:`NoteItem`
clauses covering the observed syntaxes:

* ``1.骨笄`` / ``1. 陶豆 2. 陶壶``
* ``1. 骨笄（M4:1）`` / ``1、2. 陶豆（M4:2、M4:1）``
* ``1～4.豆（M3：4、M3：2、M3：3、M3：1）``
* ``2、9.铁器（00FBH1:6、00FBH1:3）``
* ``A. 盗坑（长沙青振）`` (letter seq, ``seq_list`` empty)
* ``$1\\sim 4$ 陶豆 5.陶壶`` / ``1.00FBG1:2`` (no space)
* ``3～7. 陶豆`` (no ids allowed)
* ``0 8厘米`` scale noise -> no item
* circled ``①``..``⑳`` / ``㉑``..``㉚`` -> ``1``..``30`` as a seq label

Circled notes are split on the markers themselves, not by a text rewrite:
a marker followed only by whitespace / ``、,，.。`` accumulates into a pending
buffer, and the next marker with real text emits one clause whose seq joins
the pending numbers with ``、``.  Multiple notes are merged by the caller with
newlines.  ``extract_caption_artifacts`` is the weak caption fallback
(R-MAP-01) used only when a figure note yields no artifact ids.
"""

from __future__ import annotations

import re

from archaeopairs.models import NoteItem
from archaeopairs.text.artifact_id import _circle_digits, extract_artifacts

_CAPTION_FIG_RE = re.compile(
    r"[图圖]\s*(?:版\s*)?[0-9一二三四五六七八九十百零〇A-Za-z][0-9一二三四五六七八九十百零〇A-Za-z\-]*"
)
# One seq element may itself be a range (``1～4``); group separators join them.
_SEQ_ELEM = r"(?:\d+|[A-Za-z])(?:\s*[～~\-]\s*(?:\d+|[A-Za-z]))?"
_SEQ_LABEL = _SEQ_ELEM + r"(?:\s*[、,，]\s*" + _SEQ_ELEM + r")*"
_LABEL_RE = re.compile(
    r"(?<![\dA-Za-z])" + _SEQ_LABEL + r"\s*[.．。](?!\d)"
    # ``1.00FBG1:2``: digit-led artifact id glued to the label dot.
    r"|(?<![\dA-Za-z])(?P<glued>\d+)\s*[.．。](?=\d[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\s*[:：∶])"
)
_SIM_RE = re.compile(r"\$(?P<a>\d+)\s*\\sim\s*(?P<b>\d+)\$\s*(?P<tail>[^.．。\d]*)")
_SCALE_RE = re.compile(r"^\s*\d+\s*(?:厘米|公分|cm|CM|mm|毫米)\s*$")
_PAREN_RE = re.compile(r"[（(]([^（）()]*)[）)]")
_LINE_SPLIT_RE = re.compile(r"\s*[\r\n]+\s*")
_TOKEN_SPLIT_RE = re.compile(r"\s*[、,，]\s*")
_RANGE_RE = re.compile(r"^(\d+)\s*[～~\-]\s*(\d+)$")

# Circled seq markers: ①..⑳ are U+2460..U+2473, ㉑..㉚ are U+3251..U+325A.
_CIRCLED = {
    **{chr(0x2460 + i): str(i + 1) for i in range(20)},
    **{chr(0x3251 + i): str(21 + i) for i in range(10)},
}
_CIRCLED_WHITESPACE = " \t\r\n\u3000"
_CIRCLED_IGNORED = frozenset(_CIRCLED_WHITESPACE + "、,，.。．")


def _circled_index(text: str, start: int = 0) -> int:
    """Index of the next circled marker at/after ``start``, or ``-1``."""

    for idx in range(start, len(text)):
        if text[idx] in _CIRCLED:
            return idx
    return -1


def _body_is_empty(body: str) -> bool:
    """True when ``body`` holds only whitespace and ``、,，.。`` separators."""

    return all(ch in _CIRCLED_IGNORED for ch in body)


def _parse_circled(text: str) -> list[NoteItem]:
    """Marker-scan pass for circled notes (fix_request round 2).

    Each marker owns the text up to the next marker.  An empty body only
    accumulates its number; the first marker with real text flushes one clause
    ``seq="、".join(pending + [number])``.  Leading text before the first
    marker and a trailing pending run carry no name of their own, so they are
    dropped rather than guessed.
    """

    items: list[NoteItem] = []
    pending: list[str] = []
    marker = _circled_index(text)
    while marker != -1:
        number = _CIRCLED[text[marker]]
        nxt = _circled_index(text, marker + 1)
        body = text[marker + 1: nxt if nxt != -1 else len(text)]
        if _body_is_empty(body):
            pending.append(number)
        else:
            label = "、".join(pending + [number])
            _emit(items, label, body.strip())
            pending = []
        marker = nxt
    return items


def _expand(label: str) -> list[int]:
    out: list[int] = []
    for token in _TOKEN_SPLIT_RE.split(label.strip()):
        rng = _RANGE_RE.match(token)
        if rng:
            a, b = int(rng.group(1)), int(rng.group(2))
            if a <= b:
                out.extend(range(a, b + 1))
            continue
        if token.isdigit():
            out.append(int(token))
    return out


def _prefixed_continuation(text: str) -> int:
    """Start offset of the bare ``dddd...:n`` continuation in a caption."""

    m = re.search(r"(?<![A-Za-z0-9:：∶])([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*[:：∶]\s*\d", text)
    return m.start() if m else len(text)


def _artifacts(text: str) -> list[str]:
    """``extract_artifacts`` restricted to colon-bearing ids (R-ID-01)."""

    return [aid for aid in extract_artifacts(text) if ":" in aid]


def _ids_from(text: str, *, allow_bare_prefix: bool = False) -> list[str]:
    if not text and not allow_bare_prefix:
        return []
    body = _PAREN_RE.sub(lambda m: " " + m.group(1) + " ", text or "")
    body = _CAPTION_FIG_RE.sub(" ", body)
    if allow_bare_prefix:
        # ``....00FBG1:2`` follows a ``1.`` label; the bare digit-led prefix
        # would be swallowed as a prefixed name, so stitch it back on.
        start = _prefixed_continuation(body)
        # Strip the space between the bare prefix and its colon group so the
        # stitched text is a valid ``X:数字`` id again.
        stitched = re.sub(r"([A-Za-z0-9\-])\s*([:：∶])\s*", r"\1\2", body)
        start = _prefixed_continuation(stitched)
        ids = _artifacts(stitched[start:]) + _artifacts(stitched[:start])
    else:
        ids = _artifacts(body)
    # Keep note-local duplicates: they are the evidence text_map needs to
    # detect one artifact claimed by several seqs.  Cross-clause overlap must
    # reach the cardinality rules, never be silently deduplicated away.
    return list(ids)


def _label_bounds(chunk: str) -> list[tuple[str, int, int]]:
    bounds: list[tuple[str, int, int]] = []
    for m in _SIM_RE.finditer(chunk):
        bounds.append((f"{m.group('a')}～{m.group('b')}", m.start(), m.end()))
    for m in _LABEL_RE.finditer(chunk):
        bounds.append((m.group(0), m.start(), m.end()))
    bounds.sort(key=lambda b: b[1])
    return bounds


def _join_parenthesized_lines(text: str) -> str:
    """Join line breaks that fall inside ``（）``/``()`` id lists.

    Book XML often wraps a long artifact-id list across lines; splitting there
    would move the second id into the next clause (``seq 4、5`` losing its
    second id to ``seq 6``).
    """
    out: list[str] = []
    depth = 0
    for char in text:
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        if char in "\r\n" and depth > 0:
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def parse_note(text: str) -> list[NoteItem]:
    """Parse one figure-note string into ordered :class:`NoteItem` clauses."""

    if not text or not text.strip():
        return []
    text = _join_parenthesized_lines(text)
    # ``①骨笄（M4:1） ②陶豆（M4:2）``: circled markers are clause boundaries,
    # handled by their own scan so each marker owns its body verbatim.
    if any(ch in _CIRCLED for ch in text):
        return _parse_circled(text)

    items: list[NoteItem] = []
    for chunk in _LINE_SPLIT_RE.split(text.strip()):
        chunk = chunk.strip()
        if not chunk or _SCALE_RE.match(chunk):
            continue
        bounds = _label_bounds(chunk)
        if not bounds:
            continue
        # Text before the first label carries ids with no explicit seq (e.g.
        # ``M4:6 1. 铜舟``); attach them to the first clause.
        prefix_text = chunk[: bounds[0][1]].strip()
        for idx, (label, _start, end) in enumerate(bounds):
            stop = bounds[idx + 1][1] if idx + 1 < len(bounds) else len(chunk)
            body = chunk[end:stop]
            if idx == 0 and prefix_text:
                body = prefix_text + " " + body
            _emit(items, label.strip().rstrip(".．。 ").strip(), body)
    return items


def _emit(items: list[NoteItem], label: str, body: str) -> None:
    seq_list = _expand(label)
    # ASCII letter labels only (`str.isalpha` also accepts `、`).
    if not seq_list and not (label.isascii() and label.isalpha()):
        return
    name = _PAREN_RE.sub(" ", body).lstrip(".．。 ").strip(" ,，、;；:。．")
    ids = _ids_from(body, allow_bare_prefix=bool(seq_list))
    items.append(NoteItem(seq=label, seq_list=seq_list, name=name or None, artifact_ids=ids))


def extract_caption_artifacts(caption: str | None) -> list[str]:
    """Weak caption fallback: artifact ids inside a figure title (R-MAP-01)."""

    if not caption:
        return []
    return _ids_from(_CAPTION_FIG_RE.sub(" ", _circle_digits(caption)))
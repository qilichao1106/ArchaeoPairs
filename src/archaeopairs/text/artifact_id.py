"""Artifact-id normalization and extraction (R-ID-01..06).

Internal keys always use a half-width colon (``M4:6``). Case is preserved, and
trailing letter suffixes (``75a``) and ``-N`` sub-numbers (``8-1``) are kept as
part of the id, never collapsed onto the stem.
"""

from __future__ import annotations

import re

_CIRCLE_TO_DIGIT = {chr(0x2460 + i): str(i + 1) for i in range(9)}
_CIRCLE_TO_DIGIT[chr(0x24EA)] = "0"
_CIRCLE_TO_DIGIT.update({chr(0x2776 + i): str(i + 1) for i in range(10)})

_COLON_RE = re.compile(r"[:\uff1a\u2236]")
_GROUP = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
_BARE_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# Full id: label (with optional hyphenated prefix, e.g. ``M4-1``) plus one or
# more colon-separated groups. Suffix letters / ``-N`` stay inside a group.
_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<pre>[A-Za-z]{0,4}\d[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)"
    r"(?P<groups>(?:[:\uff1a\u2236]" + _GROUP + r")+)"
    r"(?![A-Za-z0-9])"
)
_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9:\uff1a\u2236])\d+\s*[-\u2010-\u2015~\uff5e\uff0d]\s*\d+(?![A-Za-z0-9])"
)
_SCALE_RE = re.compile(r"\d+\s*(?:厘米|公分|cm|CM|mm|毫米)")
_ELLIPSIS_RE = re.compile(r"\u2026+|\.{2,}")
_SEPARATOR_RE = re.compile(r"([,，、;；。\n])")


def _circle_digits(text: str) -> str:
    return "".join(_CIRCLE_TO_DIGIT.get(ch, ch) for ch in text)


def normalize_artifact_id(raw: str) -> str:
    """Normalize an artifact id to the internal ``prefix:group`` form.

    ``:``/``：``/``∶`` become ``:`` and whitespace around them is folded away.
    Case, suffix letters and ``-N`` sub-numbers are preserved; circled digits
    are converted to ASCII (R-ID-02).
    """

    if raw is None:
        return ""
    text = _circle_digits(str(raw)).strip()
    text = _COLON_RE.sub(":", text)
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text).strip()


def _mask_empty_ellipsis(text: str) -> str:
    """Replace ellipses between *bare* continuations with a comma.

    ``M43：75a……75b`` -> ``M43：75a，75b``; the continuation then inherits the
    prefix of the preceding full id. An ellipsis that introduces a new full id
    (``M4:6……M4:7``) is left as a hard sentence break.
    """

    def repl(match: re.Match[str]) -> str:
        after = match.string[match.end():]
        if re.match(r"[A-Za-z]{0,4}\d[A-Za-z0-9]*(?:[:：∶])", after):
            return match.group(0)
        return "，"

    return _ELLIPSIS_RE.sub(repl, text)


def extract_artifacts(text: str) -> list[str]:
    """Extract normalized artifact ids in order of first appearance.

    Only true ``X:数字`` ids are returned. Bare prefixed names such as ``Bb9``
    never produce an id on their own (name evidence only). Scale text
    (``0 8厘米``), figure numbers (``图二一二``) and figure sub-numbers
    (``图2-1-16``) are rejected. Bare continuations after a full id
    (``M43：75a……75b``) inherit that id's prefix (R-ID-06).
    """

    if not text:
        return []

    cleaned = _circle_digits(str(text))
    cleaned = _SCALE_RE.sub(" ", cleaned)
    cleaned = _RANGE_RE.sub(" ", cleaned)
    cleaned = _mask_empty_ellipsis(cleaned)

    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    current_prefix: str | None = None

    def add(offset: int, artifact_id: str) -> None:
        if artifact_id not in seen:
            seen.add(artifact_id)
            found.append((offset, artifact_id))

    cursor = 0
    for part in _SEPARATOR_RE.split(cleaned):
        if _SEPARATOR_RE.fullmatch(part):
            cursor += len(part)
            continue
        colon_ids = False
        for match in _ID_RE.finditer(part):
            prefix = match.group("pre")
            # ``X:digit`` requires a letter in the prefix; bare figure/plate
            # numbers are not artifact ids.
            if not re.search(r"[A-Za-z]", prefix):
                continue
            groups = [g for g in _COLON_RE.split(match.group("groups")) if g]
            if not any(re.search(r"\d", g) for g in groups):
                continue
            colon_ids = True
            current_prefix = prefix
            for group in groups:
                add(cursor + match.start(), normalize_artifact_id(f"{prefix}:{group}"))
        if current_prefix and not colon_ids:
            for bare in _BARE_RE.finditer(part):
                token = bare.group(0)
                if not re.search(r"\d", token):
                    continue
                # A bare label that starts with a letter and has no colon is a
                # name/prefix (``Bb9``), not a continuation of the last id.
                if re.search(r"[A-Za-z]", token):
                    continue
                add(
                    cursor + bare.start(),
                    normalize_artifact_id(f"{current_prefix}:{token}"),
                )
        cursor += len(part)

    found.sort(key=lambda item: item[0])
    return [artifact_id for _, artifact_id in found]

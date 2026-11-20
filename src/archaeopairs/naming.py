"""Figure/artifact naming rules (R-NAME-01..06, AC-07).

The output name is ``<figure number>_<seq|01>_<artifact>.png``.  All helpers
are pure: the caller owns the book-level dedup registry and passes the sequence
string exactly as decided by mapping (``None`` means "no seq" -> ``01``).
"""

from __future__ import annotations

import re

__all__ = [
    "build_image_name",
    "dedup_name",
    "extract_fig_number",
    "normalize_colons",
    "path_artifact",
]

_COLON_RE = re.compile(r"[:\uff1a\u2236]")
_CN_NUMERAL = "零〇一二三四五六七八九十百千"
# A figure number: arabic groups joined by dashes, or a chinese numeral, plus
# an optional single letter suffix (``图七a`` / ``图2-1-16b``).
_NUMBER = r"(?:\d+(?:-\d+)*|[" + _CN_NUMERAL + r"]+)"
_FIG_RE = re.compile(
    r"图版\s*(?P<plate>" + _NUMBER + r"[A-Za-z]?)"
    r"|(?P<tuo>拓片|拓本)\s*(?P<tuo_num>" + _NUMBER + r"[A-Za-z]?)"
    r"|图\s*(?P<num>" + _NUMBER + r"[A-Za-z]?)"
)


def _is_real_number(token: str) -> bool:
    """Reject descriptions that merely start with a chinese char (``图示``)."""
    return bool(re.match(r"\d|[" + _CN_NUMERAL + r"]", token))


def extract_fig_number(caption: str | None, fallback: str = "图") -> str:
    """Extract the figure number from a caption, dropping description text.

    Supports ``图2-1-16``, ``图七``, ``图二六``, ``图版204``, ``拓片三七`` and
    keeps suffixes (``图七a``, ``图2-1-16b``).  Text after the number
    (``图2-1-16 M4出土铜鼎``) is discarded; ``fallback`` is returned when no
    figure number is present.
    """
    if not caption:
        return fallback
    match = _FIG_RE.search(str(caption).strip())
    if match is None:
        return fallback
    if match.group("plate") is not None:
        token = "图版" + match.group("plate")
    elif match.group("tuo") is not None:
        token = match.group("tuo") + match.group("tuo_num")
    else:
        token = "图" + match.group("num")
    if not _is_real_number(token.lstrip("图版拓本片")):
        return fallback
    return token


def normalize_colons(text: str) -> str:
    """``:`` / ``：`` / ``∶`` -> ``-`` (R-NAME-02)."""
    return _COLON_RE.sub("-", "" if text is None else str(text))


def path_artifact(artifact_id: str) -> str:
    """Filesystem-safe artifact segment: colons become hyphens."""
    return re.sub(r"\s+", "", normalize_colons(artifact_id))


def build_image_name(fig_number: str, seq: str | None, artifact_id: str) -> str:
    """``<fig>_<seq|01>_<artifact>.png`` (R-NAME-01/05)."""
    figure = extract_fig_number(fig_number, fallback=fig_number) if fig_number else "图"
    seq_part = "01" if seq is None or not str(seq).strip() else str(seq).strip()
    return f"{figure}_{seq_part}_{path_artifact(artifact_id)}.png"


def dedup_name(name: str, registry: dict[str, int]) -> str:
    """Return a book-unique name, inserting ``_1``/``_2`` before the suffix.

    ``registry`` is shared at book level and maps every handed-out name to a
    counter, so ``a.png`` three times yields ``a.png`` / ``a_1.png`` /
    ``a_2.png``.  The chosen name is registered before it is returned.
    """
    dot = name.rfind(".")
    base, ext = (name, "") if dot <= 0 else (name[:dot], name[dot:])
    if name not in registry:
        registry[name] = 0
        return name
    counter = int(registry[name])
    while True:
        counter += 1
        candidate = f"{base}_{counter}{ext}"
        if candidate not in registry:
            registry[name] = counter
            registry[candidate] = counter
            return candidate

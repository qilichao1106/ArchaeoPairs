"""Artifact counting + five-way classification (R-IN-11..14).

Two-stage, deterministic classifier:

1. **Artifact count** from the caption/note text is the primary evidence
   (R-IN-12). ``N == 0`` short-circuits to :attr:`ImageType.DISCARDED`;
   ``N == 1`` / ``N >= 2`` then only need to decide line vs. plate.
2. **Line vs. plate** is decided from image pixels (line-drawing vs. photo /
   plate). The image is downscaled so its longest side is ``96`` px and colour
   is measured via the max-min channel range (``d``). Very low ink coverage is
   a line drawing; colourful or mid-tone images are plates/photos. Rub/facsimile
   keywords (拓片/拓本/…) force line only when the family is gray (R-IN-13);
   colour is never overridden.

R-IN-11 mapping to work lines lives in :func:`work_line_of`.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from archaeopairs.models import ImageType, WorkLine

try:  # Pillow is a declared dependency; degrade gracefully if absent.
    from PIL import Image
except Exception:  # pragma: no cover - only on a broken install
    Image = None  # type: ignore[assignment]


# ----- artifact-number recognition -----------------------------------------

_LABEL = r"[A-Za-z]{0,4}\d[A-Za-z0-9\-]*"
_ARTIFACT_RE = re.compile(
    # prefix must start at a non-alnum boundary; the chain is ``prefix:group``
    # possibly repeated. The two negative lookaheads after the chain split
    # tightly-packed ids (``M43:75a、M43:75b``) while refusing to emit a token
    # that is only a truncated prefix of the next one (``M4:6M4:7``).
    r"(?<![A-Za-z0-9])"
    r"(?P<pre>" + _LABEL + r")(?P<groups>(?:[:：∶][A-Za-z0-9\-]+)+)"
    r"(?![0-9A-Za-z\-])(?!(?:[A-Za-z][0-9]|[0-9]{2}))"
)
_ELLIPSIS_RUN_RE = re.compile(r"(?:\u2026|\.{2,})+")
_NEW_LABEL_RE = re.compile(r"[A-Za-z]{0,4}\d[A-Za-z0-9\-]*(?:[:：∶][A-Za-z0-9\-]+)+")

_RUB_WORDS = ("拓片", "拓本", "拓印", "线描", "摹写")
_PLATE_WORDS = ("图版", "圖版")

_MAX_SIDE = 96


def _canon_digits(text: str) -> str:
    """Map look-alike letters (O/o/I/l) in a numeric run to digits."""
    out = []
    for ch in text:
        if ch in "Oo":
            out.append("0")
        elif ch in "Il":
            out.append("1")
        else:
            out.append(ch)
    return "".join(out)


def _normalize_token(token: str) -> str:
    """Normalize colons to ``:``; keep case, suffix letters and ``-N``."""
    token = re.sub(r"[:：∶]", ":", token)
    return _canon_digits(token) if re.fullmatch(r"[0-9OoIl:]+", token) else token


def _artifact_tokens(text: str) -> list[str]:
    """Return normalized artifact-id tokens found in ``text``.

    ``M4:6`` -> ``M4:6``. A group that is a bare number with no prefix/colon is
    ignored so page numbers and scale text (``0 8厘米``) never count. Runs of
    ellipsis (``……``) between a digit and the *next* full id (``M4:6……M4:7``)
    become a sentence break; between two bare continuations (``75a……75b``) they
    extend the same prefix (R-ID-06), yielding ``M43:75a``/``M43:75b``/``M43:75c``.
    """
    if not text:
        return []

    def _collapse_run(match: "re.Match[str]") -> str:
        start, end = match.start(), match.end()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if before.isdigit() and _NEW_LABEL_RE.match(text, end):
            return "，"
        return "："

    text = _ELLIPSIS_RUN_RE.sub(_collapse_run, text)
    text = re.sub(r"[:：∶]{2,}", "：", text)

    tokens: list[str] = []
    for match in _ARTIFACT_RE.finditer(text):
        prefix = match.group("pre")
        groups = [g for g in re.split(r"[:：∶]", match.group("groups")) if g]
        for group in groups:
            group_norm = _canon_digits(group) if re.fullmatch(r"[0-9OoIl]+", group) else group
            tokens.append(_normalize_token(f"{prefix}:{group_norm}"))
    return [tok for tok in tokens if re.search(r"\d", tok)]

def count_artifacts(caption: str | None, figure_note: str | None) -> int:
    """Count distinct artifact numbers (R-ID-06 suffixes kept as distinct).

    The figure note (图注) is the primary source: when it contains any asset
    number its tokens are used as-is. The caption (图题) is only a fallback,
    consulted when the note is missing or carries no asset number. Returns
    ``0`` when neither has an id. Duplicates are de-duplicated by normalized
    token.
    """
    for text in (figure_note, caption):
        if not text:
            continue
        tokens = _artifact_tokens(text)
        if tokens:
            return len(dict.fromkeys(tokens))
    return 0


# ----- pixel signals --------------------------------------------------------

def _load_signals(image_path: str | None) -> tuple[float, float, float] | None:
    """Return ``(pct20, mean_chroma, mid_ratio)`` or ``None`` if unreadable."""
    if not image_path or Image is None:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            if w == 0 or h == 0:
                return None
            scale = _MAX_SIDE / max(w, h)
            if scale < 1.0:
                new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
                rgb = rgb.resize(new_size, Image.Resampling.BILINEAR)
            arr = np.asarray(rgb, dtype=np.int16)
    except Exception:
        return None

    diff = arr.max(axis=2) - arr.min(axis=2)
    pct20 = float((diff > 20).mean() * 100.0)
    mean_chroma = float(diff.mean())
    gray = arr.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    mid_ratio = float(((gray > 64) & (gray < 192)).mean() * 100.0)
    return pct20, mean_chroma, mid_ratio


def _family(signals: tuple[float, float, float] | None) -> str | None:
    """Return ``"color"``, ``"gray"`` or ``"line"`` from pixel signals."""
    if signals is None:
        return None
    pct20, mean_chroma, mid_ratio = signals
    if pct20 >= 5.0 or (mean_chroma >= 8.0 and pct20 >= 1.0):
        return "color"
    return "gray" if mid_ratio >= 15.0 else "line"


def _has_kw(text: str | None, words: tuple[str, ...]) -> bool:
    return bool(text) and any(word in text for word in words)


def classify_image_type(
    caption: str | None,
    figure_note: str | None,
    image_path: str | Path | None,
) -> ImageType:
    """Classify a figure into one of the five :class:`ImageType` values."""
    count = count_artifacts(caption, figure_note)
    if count == 0:
        return ImageType.DISCARDED

    combined = " ".join(t for t in (caption, figure_note) if t)
    family = _family(_load_signals(str(image_path) if image_path else None))

    if family is None:
        # Image unreadable/missing: fall back to keywords (R-IN-04/R-IN-13).
        is_line = not _has_kw(combined, _PLATE_WORDS) or _has_kw(combined, _RUB_WORDS)
    elif family == "line":
        is_line = True
    elif family == "gray":
        is_line = _has_kw(combined, _RUB_WORDS)
    else:  # color is never overridden by keywords
        is_line = False

    if count == 1:
        return ImageType.SINGLE_LINE if is_line else ImageType.SINGLE_PLATE
    return ImageType.MULTI_LINE if is_line else ImageType.MULTI_PLATE


def work_line_of(image_type: ImageType) -> WorkLine:
    """Map a five-way type to its work line (R-IN-11)."""
    mapping = {
        ImageType.SINGLE_LINE: WorkLine.SINGLE_LINE,
        ImageType.SINGLE_PLATE: WorkLine.SINGLE_PLATE,
        ImageType.MULTI_LINE: WorkLine.MULTI_LINE,
        ImageType.MULTI_PLATE: WorkLine.ARCHIVE,
        ImageType.DISCARDED: WorkLine.ARCHIVE,
    }
    if not isinstance(image_type, ImageType):
        image_type = ImageType(image_type)
    return mapping[image_type]


def classify(
    caption: str | None,
    figure_note: str | None,
    image_path: str | Path | None,
) -> tuple[ImageType, WorkLine]:
    """Convenience: ``image_type`` plus its derived :class:`WorkLine`."""
    image_type = classify_image_type(caption, figure_note, image_path)
    return image_type, work_line_of(image_type)

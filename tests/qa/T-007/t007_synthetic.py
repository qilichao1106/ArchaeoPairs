"""Synthetic factories for the T-007 acceptance tests.

Everything is built in memory so the frozen suite never reads ``books/`` or
writes outside pytest's own temporary directories.

The module name is T-007-specific: ``tests/qa/T-006/synthetic.py`` already owns
the top-level name ``synthetic`` when the whole suite is collected.
"""

from __future__ import annotations

from archaeopairs.models import SeqLabel, TextMapping, View


def make_view(
    view_id: int,
    bbox: tuple[int, int, int, int],
    *,
    area: int | None = None,
    mask_rle: str = "",
    incomplete: bool = False,
) -> View:
    """Build a View; ``area`` defaults to the bbox area used by the binder."""
    x0, y0, x1, y1 = bbox
    if area is None:
        area = max(0, x1 - x0) * max(0, y1 - y0)
    return View(
        view_id=view_id,
        bbox=bbox,
        area=area,
        mask_rle=mask_rle,
        incomplete=incomplete,
    )


def make_label(text: str, cx: int, cy: int, *, half: int = 2) -> SeqLabel:
    """Build a small SeqLabel bbox whose centre is exactly ``(cx, cy)``."""
    return SeqLabel(text=text, bbox=(cx - half, cy - half, cx + half, cy + half))


def make_mapping(
    seq_to_artifacts: dict[str, list[str]] | None = None,
    caption_artifacts: list[str] | None = None,
    *,
    case_type: str = "rule_a",
    conflicts: list[str] | None = None,
) -> TextMapping:
    """Build a TextMapping without touching the text parser."""
    return TextMapping(
        seq_to_artifacts=dict(seq_to_artifacts or {}),
        caption_artifacts=list(caption_artifacts or []),
        case_type=case_type,
        conflicts=list(conflicts or []),
    )


def build_map(views, labels, mapping: TextMapping, **kwargs):
    """Bind synthetic labels to views, then assemble the ArtifactMap."""
    from archaeopairs.mapping import bind_labels_to_views, build_artifact_map

    bindings = bind_labels_to_views(views, labels)
    kwargs.setdefault("book_id", "book-synthetic")
    kwargs.setdefault("figure_id", "fig-synthetic")
    return build_artifact_map(views, bindings, mapping, **kwargs)
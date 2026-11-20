"""Per-figure orchestration for the four work lines (T-010, AC-01/04/06).

One figure goes through at most one of::

    L1 multi_line    : text mapping -> segment -> OCR -> bind/group ->
                       ArtifactMap -> scale bind -> compose -> PairRecord
    L2/L3 single_*   : one unique artifact -> whole image -> PairRecord
    L4 archive       : EXCLUDED, zero pairs

L4 never runs segmentation, OCR or composition (R-L4-02).  Mistakes are
fail-closed: composition is only attempted on a clean mapping (no alarms and
no conflicts, no unbound items), and a figure that cannot be shown to satisfy
that becomes ``pending_review`` with evidence instead of a guessed image.

I/O is injected (``PipelineConfig.writer``) so tests never touch the network
or the disk: :class:`NullWriter` is the default no-op writer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from PIL import Image

import numpy as np

from archaeopairs.classify import classify, work_line_of
from archaeopairs.compose import compose_unit
from archaeopairs.mapping import (
    apply_scale_bindings,
    bind_labels_to_views,
    bind_scales,
    build_artifact_map,
    build_text_mapping,
    group_views,
    normalize_seq_label,
)
from archaeopairs.models import (
    ArtifactMap,
    ArtifactUnit,
    FigureInput,
    FigureResult,
    ImageType,
    MappingRef,
    OcrResult,
    PairRecord,
    Provenance,
    ScaleBar,
    ScaleBinding,
    SeqLabel,
    TextArtifact,
    View,
    WorkLine,
)
from archaeopairs.naming import build_image_name, dedup_name, extract_fig_number
from archaeopairs.ocr import HybridOCRProvider, PaddleOCRProvider, VlmOCRProvider
from archaeopairs.text import (
    extract_caption_artifacts,
    parse_note,
    split_body,
)
from archaeopairs.text.artifact_id import extract_artifacts
from archaeopairs.vision import load_image, segment_views

__all__ = [
    "NullWriter",
    "PipelineConfig",
    "Writer",
    "process_book",
    "process_figure",
]

LONG_TEXT_LIMIT = 2000


@runtime_checkable
class Writer(Protocol):
    """Output sink: one PNG, all pairs of a book, the book ledger."""

    def write_image(self, name: str, image: np.ndarray) -> str: ...

    def write_pairs(self, records: list[dict]) -> None: ...

    def write_ledger(self, rows: list[dict]) -> None: ...


class NullWriter:
    """No-op writer: returns the proposed name, persists nothing."""

    def write_image(self, name: str, image: np.ndarray) -> str:
        return name

    def write_pairs(self, records: list[dict]) -> None:
        return None

    def write_ledger(self, rows: list[dict]) -> None:
        return None


@dataclass
class PipelineConfig:
    ocr: Any = None            # OCRProvider; None -> hybrid VLM + Paddle
    writer: Writer | None = None
    name_registry: dict[str, int] | None = None
    vlm_client: Any = None
    paddle_engine: Any = None

    def resolved_writer(self) -> Writer:
        if self.writer is None:
            return NullWriter()
        return self.writer

    def resolved_ocr(self) -> Any:
        if self.ocr is not None:
            return self.ocr
        client = self.vlm_client
        if client is None:
            from archaeopairs.vlm.client import VlmClient

            client = VlmClient()
        return HybridOCRProvider(
            VlmOCRProvider(client), PaddleOCRProvider(self.paddle_engine)
        )


# --- small helpers ---------------------------------------------------------


def _unique(values) -> list:
    seen: set = set()
    out: list = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _alarms_from_map(amap: ArtifactMap) -> list[str]:
    alarms = [str(a) for a in amap.alarms if str(a).startswith("E")]
    for item in amap.unbound_seqs:
        alarms.append("E001")
    if amap.unbound_groups:
        alarms.append("E005")
    return _unique(alarms)


def _views_by_id(views: list[View]) -> dict[int, View]:
    return {view.view_id: view for view in views}


def _box_inside(inner: tuple, outer: tuple, tol: int = 2) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _box_area(box: tuple) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _inter_area(a: tuple, b: tuple) -> int:
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return w * h


def _aux_owned(view_box: tuple, aux_box: tuple) -> bool:
    """A view belongs to OCR when it is contained in, or mostly overlaps, an
    auxiliary box.  The dilation pad makes glyph/scale views slightly larger
    than their OCR bbox, so containment alone is not enough; a drawing that
    merely surrounds a small label has a tiny overlap ratio and stays."""
    if _box_inside(view_box, aux_box):
        return True
    inter = _inter_area(view_box, aux_box)
    if inter == 0:
        return False
    view_area = _box_area(view_box)
    aux_area = _box_area(aux_box)
    return (view_area > 0 and inter / view_area >= 0.35) or (
        aux_area > 0 and view_area <= aux_area * 1.5
        and inter / aux_area >= 0.8)


def _image_shape(path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _sane_ocr(ocr: OcrResult, image_shape: tuple[int, int] | None) -> OcrResult:
    """Drop absurd OCR boxes (a whole image as one 'label') before binding."""
    if not image_shape:
        return ocr
    width, height = image_shape
    limit = 0.1 * width * height if width > 0 and height > 0 else None

    def ok(box) -> bool:
        if box[2] <= box[0] or box[3] <= box[1]:
            return False
        return limit is None or _box_area(tuple(box)) <= limit

    return ocr.model_copy(update={
        "seqs": [s for s in ocr.seqs if ok(tuple(s.bbox))],
        "scales": [s for s in ocr.scales if ok(tuple(s.bbox))],
        "texts": [s for s in ocr.texts if ok(tuple(s.bbox))],
    })


def _box_gap(a: tuple, b: tuple) -> float:
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return float((dx * dx + dy * dy) ** 0.5)


def _glyph_owned(view_box: tuple, label_box: tuple,
                 gap_max: float = 12.0) -> bool:
    """Small view sitting on/near a seq box is that label's own glyph."""
    if (label_box[2] - label_box[0] > 60 or label_box[3] - label_box[1] > 60
            or view_box[2] - view_box[0] > 60
            or view_box[3] - view_box[1] > 60):
        return False
    view_area = _box_area(view_box)
    label_area = _box_area(label_box)
    if label_area <= 0 or view_area <= 0 or view_area > 4 * label_area:
        return False
    return _inter_area(view_box, label_box) > 0 or _box_gap(
        view_box, label_box) <= gap_max


def _sanitize_seq_labels(seqs: list, views: list[View]) -> list:
    """Drop OCR duplicates that cannot be printed seq labels.

    A VLM occasionally reports one number twice: the real label in the margin
    and a false box on hatching inside a drawing.  Both would bind to different
    views and merge two artefacts into one unit.  Duplicates are kept only when
    both sit on a small glyph (a legitimate repeated label / 1:N view); when no
    glyph reference exists the smallest box wins.
    """
    groups: dict[str, list] = {}
    passthrough: list = []
    for label in seqs or []:
        key = normalize_seq_label(getattr(label, "text", "") or "")
        if key is None:
            passthrough.append(label)
        else:
            groups.setdefault(key, []).append(label)

    kept = list(passthrough)
    small = [tuple(view.bbox) for view in views
             if (view.bbox[2] - view.bbox[0] <= 60
                 and view.bbox[3] - view.bbox[1] <= 60)]
    for items in groups.values():
        if len(items) <= 1:
            kept.extend(items)
            continue
        scored = []
        for label in items:
            box = tuple(label.bbox)
            gaps = [_box_gap(box, glyph) for glyph in small]
            scored.append((min(gaps) if gaps else float("inf"),
                           _box_area(box), label))
        best = min(gap for gap, _area, _label in scored)
        if best <= 20.0:
            kept.extend(label for gap, _area, label in scored
                        if gap <= best + 2.0)
        else:
            kept.append(min(items, key=lambda label: _box_area(tuple(label.bbox))))
    return kept


def _expand_scale_boxes(image_path, scales: list[ScaleBar]) -> list[ScaleBar]:
    """Grow an OCR scale box down to the printed bar line it labels.

    VLM boxes often cover only ``0 ... 4厘米`` and stop above the horizontal
    bar, so cropping by the raw box loses the bar itself.  A long horizontal
    ink run within 48 px below the text is the bar; include it and its ticks.
    """
    if not scales:
        return scales
    try:
        with Image.open(image_path) as opened:
            gray = np.asarray(opened.convert("L"))
    except Exception:
        return scales
    height, width = gray.shape[:2]
    out: list[ScaleBar] = []
    for scale in scales:
        x0, y0, x1, y1 = (int(v) for v in scale.bbox)
        pad_x = max(16, int(0.2 * max(1, x1 - x0)))
        x0c, x1c = max(0, x0 - pad_x), min(width, x1 + pad_x)
        y0c, y1c = max(0, y0), min(height, y1 + 48)
        if x1c <= x0c or y1c <= y0c:
            out.append(scale)
            continue
        ink = gray[y0c:y1c, x0c:x1c] < 160
        min_run = max(20, int(0.3 * (x1c - x0c)))
        bar_y = None
        run_x0, run_x1 = x1c, x0c
        for row in range(ink.shape[0]):
            line = ink[row]
            if not line.any():
                continue
            # longest run of consecutive ink pixels in this row
            padded = np.concatenate(([0], line.astype(np.int8), [0]))
            edges = np.flatnonzero(np.diff(padded))
            starts, ends = edges[0::2], edges[1::2]
            lengths = ends - starts
            if lengths.size == 0:
                continue
            longest = int(lengths.max())
            if longest < min_run:
                continue
            index = int(np.argmax(lengths))
            bar_y = max(bar_y or 0, y0c + row + 1)
            run_x0 = min(run_x0, x0c + int(starts[index]))
            run_x1 = max(run_x1, x0c + int(ends[index]))
        if bar_y is None:
            out.append(scale)
            continue
        bbox = (min(x0c, run_x0), y0, max(x1c, run_x1), max(y1, bar_y + 1))
        out.append(scale.model_copy(update={"bbox": bbox}))
    return out


def _text_owned(view_box: tuple, text_box: tuple) -> bool:
    """Text boxes may remove glyph-sized views, not drawings they cross.

    A VLM sometimes reports a bogus text block over a drawing (e.g. a whole
    vessel read as "I"); letting that block claim the drawing deletes a real
    artefact.  Large views are only text-owned when almost wholly covered.
    """
    if view_box[2] - view_box[0] <= 60 and view_box[3] - view_box[1] <= 60:
        return _aux_owned(view_box, text_box)
    if _box_inside(view_box, text_box):
        return True
    view_area = _box_area(view_box)
    return view_area > 0 and _inter_area(view_box, text_box) / view_area >= 0.75


def _glyph_candidate_boxes(views: list[View], ocr: OcrResult,
                           image_shape: tuple[int, int] | None) -> list[tuple]:
    """Segmented small components that can be printed seq labels.

    Text lines, scale readings and the top legend band are excluded; digits
    printed side by side (``10``) are merged into one label box.
    """
    if not image_shape:
        return []
    height = image_shape[1]
    text_boxes = [tuple(t.bbox) for t in ocr.texts
                  if t.bbox[3] - t.bbox[1] <= 60]
    scale_boxes = [tuple(s.bbox) for s in ocr.scales]

    def centre(box: tuple) -> tuple[float, float]:
        return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0

    def inside(box: tuple, outer: tuple, tol: float = 2.0) -> bool:
        cx, cy = centre(box)
        return (outer[0] - tol <= cx <= outer[2] + tol
                and outer[1] - tol <= cy <= outer[3] + tol)

    boxes: list[tuple] = []
    for view in views:
        box = tuple(view.bbox)
        width, height_ = box[2] - box[0], box[3] - box[1]
        if width > 60 or height_ > 60 or width < 4 or height_ < 6:
            continue
        if centre(box)[1] < 0.03 * height:
            continue
        if any(inside(box, text) for text in text_boxes):
            continue
        if any(inside(box, scale) for scale in scale_boxes):
            continue
        boxes.append(box)

    boxes.sort(key=lambda box: (int(centre(box)[1] // 20), box[0]))
    merged: list[tuple] = []
    for box in boxes:
        if merged:
            last = merged[-1]
            overlap = (min(box[3], last[3]) - max(box[1], last[1]))
            same_line = (overlap >= 0.5 * min(box[3] - box[1], last[3] - last[1])
                         and abs(centre(box)[1] - centre(last)[1])
                         <= 0.5 * min(box[3] - box[1], last[3] - last[1]))
            gap = box[0] - last[2]
            if same_line and 0 <= gap <= 6:
                merged[-1] = (last[0], min(last[1], box[1]),
                              max(last[2], box[2]), max(last[3], box[3]))
                continue
        merged.append(box)
    return merged


def _read_glyph_labels(ocr, image_path, boxes: list[tuple]) -> list[SeqLabel]:
    """Ask the OCR provider to read the character in each glyph box."""
    reader = getattr(ocr, "read_glyphs", None)
    if not boxes or not callable(reader):
        return []
    try:
        texts = reader(image_path, boxes)
    except Exception:
        return []
    if not isinstance(texts, (list, tuple)) or len(texts) != len(boxes):
        return []
    labels: list[SeqLabel] = []
    for box, text in zip(boxes, texts):
        seq_id = normalize_seq_label(text or "")
        if seq_id is None:
            continue
        labels.append(SeqLabel(text=seq_id, bbox=box, conf=0.9))
    return labels


def _drop_aux_glyph_labels(labels: list[SeqLabel],
                           ocr: OcrResult) -> list[SeqLabel]:
    """Remove glyph candidates that OCR later identified as text or scale."""
    boxes = ([tuple(t.bbox) for t in ocr.texts if t.bbox[3] - t.bbox[1] <= 60]
             + [tuple(s.bbox) for s in ocr.scales])

    def inside(box: tuple, outer: tuple, tol: float = 2.0) -> bool:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        return (outer[0] - tol <= cx <= outer[2] + tol
                and outer[1] - tol <= cy <= outer[3] + tol)

    return [label for label in labels
            if not any(inside(tuple(label.bbox), box) for box in boxes)]


def _filter_aux_views(views: list[View], ocr: OcrResult,
                      image_shape: tuple[int, int] | None = None) -> list[View]:
    """Drop views that are just scale bars or sequence-label glyphs.

    Those regions are owned by OCR and must not become artefact views.  Small
    glyphs in the top legend band are dropped even when the OCR text box omits
    their leading number; otherwise one stray legend digit makes the whole
    figure dirty.  View ids are re-indexed contiguously.
    """
    scale_boxes = [tuple(s.bbox) for s in ocr.scales]
    text_boxes = [tuple(t.bbox) for t in ocr.texts]
    seq_boxes = [tuple(s.bbox) for s in ocr.seqs]
    legend_limit = 0.03 * image_shape[1] if image_shape else None
    kept = []
    for view in views:
        box = tuple(view.bbox)
        if legend_limit is not None and (
                box[2] - box[0] <= 60 and box[3] - box[1] <= 60
                and (box[1] + box[3]) / 2.0 < legend_limit):
            continue
        if any(_aux_owned(box, a) or _glyph_owned(box, a) for a in scale_boxes):
            continue
        if any(_text_owned(box, a) for a in text_boxes):
            continue
        if any(_aux_owned(box, a) or _glyph_owned(box, a) for a in seq_boxes):
            continue
        kept.append(view)
    return [v.model_copy(update={"view_id": i}) for i, v in enumerate(kept)]


def _oversized_units(amap: ArtifactMap, views: list[View],
                     image_shape: tuple[int, int] | None,
                     limit: float = 0.7) -> set[str]:
    """Units whose view union spans most of the figure (likely merged noise)."""
    if not image_shape:
        return set()
    width, height = image_shape
    total = width * height
    if total <= 0:
        return set()
    by_id = _views_by_id(views)
    oversized: set[str] = set()
    for unit in amap.units:
        boxes = [tuple(by_id[vid].bbox) for vid in unit.view_ids if vid in by_id]
        if not boxes:
            continue
        x0 = min(box[0] for box in boxes)
        y0 = min(box[1] for box in boxes)
        x1 = max(box[2] for box in boxes)
        y1 = max(box[3] for box in boxes)
        area = _box_area((x0, y0, x1, y1))
        if area > limit * total:
            oversized.add(unit.artifact_id)
            continue
        # Three or more views spanning most of the figure usually means a
        # misread seq merged neighbouring drawings, not a legitimate
        # front/side/top set.
        if len(unit.view_ids) >= 3 and (
                (y1 - y0) > 0.6 * height or (x1 - x0) > 0.6 * width):
            oversized.add(unit.artifact_id)
    return oversized


def _aux_contaminated_units(amap: ArtifactMap,
                            views: list[View]) -> set[str]:
    """Units that still hold a glyph-sized view or a duplicated scale bar."""
    small = {view.view_id for view in views
             if view.bbox[2] - view.bbox[0] <= 60
             and view.bbox[3] - view.bbox[1] <= 60}
    scale_like = {view.view_id for view in views
                  if view.bbox[3] - view.bbox[1] <= 25
                  and view.bbox[2] - view.bbox[0] >= 40}
    bad: set[str] = set()
    for unit in amap.units:
        if (small | scale_like).intersection(unit.view_ids):
            bad.add(unit.artifact_id)
            continue
        scale_ids = [int(binding.get("scale_id", -1))
                     for binding in unit.scale_bindings
                     if isinstance(binding, dict)]
        if len(scale_ids) != len(set(scale_ids)):
            bad.add(unit.artifact_id)
    return bad


def _fill_unique_scale(bindings_by_group, scales):
    """With exactly one scale, copy it to groups that L1 left unbound.

    A single printed bar is the figure's global scale; OCR may miss some of its
    prefix numbers, so L1-only binding would wrongly leave groups without a
    bar.  Returns (bindings, filled_count).
    """
    if len(scales or []) != 1:
        return bindings_by_group, 0
    scale = scales[0]
    filled = 0
    for binds in bindings_by_group:
        if binds:
            continue
        binds.append(ScaleBinding(
            scale_id=0, source="L2_unique_shared", shared=True,
            text=str(getattr(scale, "text", "") or ""),
            value=getattr(scale, "value", None),
            unit=getattr(scale, "unit", None),
            prefix_nos=[str(n) for n in (getattr(scale, "prefix_nos", None) or [])],
        ))
        filled += 1
    return bindings_by_group, filled


def _note_names(note_items) -> dict[str, str]:
    """Map printed seq id -> artefact name from the figure note."""
    names: dict[str, str] = {}
    for item in note_items or []:
        if not item.name:
            continue
        for seq in item.seq_list or []:
            names.setdefault(str(seq), item.name)
    return names


def _named_unit(unit: ArtifactUnit, names: dict[str, str]) -> ArtifactUnit:
    if unit.artifact_name or not names:
        return unit
    found = {names[seq] for seq in unit.seq_ids if seq in names}
    if len(found) == 1:
        return unit.model_copy(update={"artifact_name": found.pop()})
    return unit


def _note_name_for_id(note_items, artifact_id: str) -> str | None:
    for item in note_items or []:
        if artifact_id in item.artifact_ids and item.name:
            return item.name
    return None


def _seq_part(unit: ArtifactUnit) -> str | None:
    """Naming seq: single seq, comma-joined seq string, or ``None`` (=01)."""
    seqs = [str(s) for s in unit.seq_ids if str(s).strip()]
    if not seqs:
        return None
    return seqs[0] if len(seqs) == 1 else ",".join(seqs)


def _scales_by_id(scales: list[ScaleBar]) -> dict[int, ScaleBar]:
    return {index: scale for index, scale in enumerate(scales)}


def _binding_meta(binding: Any, unit: ArtifactUnit) -> dict:
    if isinstance(binding, dict):
        data = dict(binding)
    else:
        data = binding.model_dump()
    data["unit_id"] = unit.artifact_id
    for key in ("seq_ids", "view_ids", "group_ids", "line", "case",
                "status", "confidence", "whole_image"):
        data[key] = getattr(unit, key)
    return data


def _figure_payload(fig: FigureInput) -> dict:
    return fig.model_dump()


# --- Pair construction -----------------------------------------------------


_BODY_CACHE: dict[str, tuple[list[TextArtifact], dict[str, TextArtifact]]] = {}
_BODY_CACHE_LIMIT = 32


def _body_artifacts(paras: list[dict]) -> list[TextArtifact]:
    """``split_body`` memoised on the paragraph content (books share a body)."""
    key = repr(paras)
    hit = _BODY_CACHE.get(key)
    if hit is None:
        artifacts = split_body(paras)
        if len(_BODY_CACHE) >= _BODY_CACHE_LIMIT:
            _BODY_CACHE.clear()
        hit = (artifacts, {a.artifact_id: a for a in artifacts})
        _BODY_CACHE[key] = hit
    return hit[0]


def _body_artifact_ids(paras: list[dict]) -> list[TextArtifact]:
    return _body_artifacts(paras)


def _is_toc_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "...." in stripped or "····" in stripped:
        return True
    if "……" in stripped and stripped[-1:].isdigit():
        return True
    return False


def _clean_toc_text(text: str) -> str:
    return "\n".join(line for line in text.splitlines()
                     if not _is_toc_line(line)).strip()


def _relevant_paras(fig: FigureInput, target_ids: set[str]) -> list[dict]:
    """Body paragraphs that mention one of the figure's artifact ids.

    ``FigureInput.body_paras`` is the whole book body; without this filter
    every figure would see every other artifact and raise spurious
    ``body_artifact_unmapped`` conflicts.  TOC lines mention ids too, so they
    are stripped from each paragraph before splitting.
    """
    if not target_ids:
        return []
    out: list[dict] = []
    for para in fig.body_paras:
        text = _clean_toc_text(str(para.get("text", "")))
        if not text:
            continue
        if set(extract_artifacts(text)) & target_ids:
            out.append({**para, "text": text})
    return out


def _text_index(artifacts: list[TextArtifact]) -> dict[str, TextArtifact]:
    return {artifact.artifact_id: artifact for artifact in artifacts}


def _build_pair(
    *, fig: FigureInput, unit: ArtifactUnit, line: WorkLine,
    source_role: str, image_path: str, figure_number: str,
    text: TextArtifact | None, flags: list[str], review: bool,
    shared_image: bool,
) -> PairRecord:
    description = text.text if text is not None and text.text else None
    quality = list(flags)
    if description is None:
        quality.append("no_text")
        review = True
    text_length = len(description) if description is not None else 0
    if text_length > LONG_TEXT_LIMIT:
        quality.append("long_text")
        review = True
    if not unit.scale_bindings:
        quality.append("no_scale")
    if shared_image:
        quality.append("shared_image")
    shared_group = unit.evidence.get("shared_group")
    mapping = MappingRef(
        artifact_id=unit.artifact_id,
        seq_ids=list(unit.seq_ids),
        view_ids=list(unit.view_ids),
        scale_ids=[int(b["scale_id"]) for b in unit.scale_bindings],
        scale_sources=[str(b.get("source", "unknown"))
                       for b in unit.scale_bindings],
        confidence=float(unit.confidence),
        line=line,
        source_role=source_role,
    )
    provenance = Provenance(
        mapping=mapping,
        source_para_ids=list(text.source_para_ids) if text else [],
        art_source=(unit.source if unit.source in
                    ("figure_note", "caption", "text", "manual") else None),
        case=unit.case,
        shared_group=("shared_group" if shared_group else None),
    )
    return PairRecord(
        book_id=fig.book_id,
        figure_id=fig.figure_id,
        artifact_id=unit.artifact_id,
        artifact_name=unit.artifact_name,
        figure_number=figure_number,
        source_role=source_role,
        image_path=image_path,
        image_merge_mode="line_only" if source_role == "line" else "plate_only",
        description_text=description,
        text_length=text_length,
        provenance=provenance,
        quality_flags=_unique(quality),
        status="review" if review else "output",
    )


def _ledger_row(
    *, fig: FigureInput, unit: ArtifactUnit, line: WorkLine,
    source_role: str, pair: PairRecord, seq: str | None,
    status: str, extra: dict | None = None,
) -> dict:
    row = {
        "book_id": fig.book_id,
        "figure_id": fig.figure_id,
        "artifact_id": unit.artifact_id,
        "seq_ids": list(unit.seq_ids),
        "seq": seq,
        "view_ids": list(unit.view_ids),
        "group_ids": list(unit.group_ids),
        "scale_ids": list(pair.provenance.mapping.scale_ids),
        "scale_sources": list(pair.provenance.mapping.scale_sources),
        "line": line.value if isinstance(line, WorkLine) else str(line),
        "source_role": source_role,
        "case_type": unit.case,
        "confidence": float(unit.confidence),
        "image_path": pair.image_path,
        "quality_flags": list(pair.quality_flags),
        "status": status,
        "source": unit.source,
        "shared": bool(unit.evidence.get("shared_group")),
        "alarms": [],
        "conflicts": [],
        "unbound": {},
        "artifact_map": None,
    }
    if extra:
        row.update(extra)
    return row


# --- L1 --------------------------------------------------------------------


def _l1(fig: FigureInput, cfg: PipelineConfig) -> tuple:
    ocr = cfg.resolved_ocr()
    note_items = parse_note(fig.figure_note) if fig.figure_note else []
    caption_artifacts = extract_caption_artifacts(fig.caption)
    target_ids = {a for item in note_items for a in item.artifact_ids}
    target_ids.update(caption_artifacts)
    body_artifacts = [
        artifact for artifact in _body_artifacts(_relevant_paras(fig, target_ids))
        if artifact.artifact_id in target_ids
    ]
    text_mapping = build_text_mapping(
        note_items, caption_artifacts, body_artifacts
    )
    views = segment_views(fig.media_path)
    image_shape = _image_shape(fig.media_path)
    # Both VLM calls are independent; run them together to halve L1 latency.
    # Candidate boxes here only need geometry (size + top band); OCR text and
    # scale boxes arrive later and prune scale digits from the glyph labels.
    pre_boxes = _glyph_candidate_boxes(
        views, OcrResult(seqs=[], scales=[], texts=[], source="vlm"),
        image_shape)
    scale_reader = getattr(ocr, "read_scales", None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_ocr = pool.submit(
            scale_reader if callable(scale_reader) else ocr.read,
            fig.media_path)
        pending_glyphs = pool.submit(
            _read_glyph_labels, ocr, fig.media_path, pre_boxes)
        try:
            ocr_result: OcrResult = pending_ocr.result()
        except Exception:
            # A malformed scales-only reply must not fail the whole figure;
            # the full OCR path has its own retry budget and still yields scales.
            if not callable(scale_reader):
                raise
            ocr_result = ocr.read(fig.media_path)
        glyph_labels = pending_glyphs.result()
    if not isinstance(ocr_result, OcrResult):
        raise TypeError(
            f"OCR provider returned {type(ocr_result).__name__}, expected OcrResult"
        )

    ocr_result = _sane_ocr(ocr_result, image_shape)
    if not ocr_result.scales and callable(scale_reader):
        # VLM occasionally misses a printed bar on the first pass; one cheap
        # retry is cheaper than publishing every unit with no_scale.
        retry = scale_reader(fig.media_path)
        if isinstance(retry, OcrResult) and retry.scales:
            ocr_result = ocr_result.model_copy(update={
                "scales": retry.scales,
                "texts": retry.texts or ocr_result.texts,
            })
    ocr_result = ocr_result.model_copy(update={
        "scales": _expand_scale_boxes(fig.media_path, list(ocr_result.scales)),
    })
    glyph_labels = _drop_aux_glyph_labels(glyph_labels, ocr_result)
    if not glyph_labels and callable(scale_reader):
        # Glyph grid failed or found nothing: fall back to whole-image seqs.
        full = ocr.read(fig.media_path)
        ocr_result = ocr_result.model_copy(update={"seqs": list(full.seqs)})
    # Whole-image box coordinates drift between VLM calls; segmentation gives
    # exact glyph boxes, so read each digit from its crop when possible.
    ocr_result = ocr_result.model_copy(update={
        "seqs": glyph_labels
        or _sanitize_seq_labels(list(ocr_result.seqs), views),
    })
    views = _filter_aux_views(views, ocr_result, image_shape)
    bindings = bind_labels_to_views(views, list(ocr_result.seqs))
    all_unlabeled_rule_b = bool(
        views and note_items and not bindings
        and any(item.artifact_ids for item in note_items)
        and text_mapping.case_type in ("rule_b", "rule_a")
    )
    amap = build_artifact_map(
        views, bindings, text_mapping,
        book_id=fig.book_id, figure_id=fig.figure_id,
        line=WorkLine.MULTI_LINE.value,
        all_unlabeled_rule_b=all_unlabeled_rule_b,
    )
    groups, _unbound = group_views(
        views, bindings, all_unlabeled_rule_b=all_unlabeled_rule_b
    )
    bindings_by_group, _records, scale_alarms = bind_scales(
        groups, list(ocr_result.scales)
    )
    bindings_by_group, filled = _fill_unique_scale(
        bindings_by_group, list(ocr_result.scales))
    # Groups without a Unit only carry contamination/noise; their missing bar
    # must not block Units that all have one.
    if amap.units and all(unit.scale_bindings or bindings_by_group[gid]
                          for unit in amap.units
                          for gid in (unit.group_ids or []) if gid < len(bindings_by_group)):
        scale_alarms = [a for a in scale_alarms
                        if a != "E007" and not str(a).startswith("group_no_scale:")]
    amap = apply_scale_bindings(amap, bindings_by_group)
    amap = amap.model_copy(update={"alarms": _unique(list(amap.alarms) + list(scale_alarms))})
    oversized = _oversized_units(amap, views, image_shape)
    contaminated = _aux_contaminated_units(amap, views)
    blocked = oversized | contaminated
    if blocked:
        amap = amap.model_copy(update={
            "units": [
                unit.model_copy(update={"status": "review"})
                if unit.artifact_id in blocked else unit
                for unit in amap.units
            ],
            "alarms": _unique(
                list(amap.alarms)
                + [f"unit_oversized:{a}" for a in sorted(oversized)]
                + [f"unit_aux_contaminated:{a}" for a in sorted(contaminated)]),
        })
    names = _note_names(note_items)
    if names:
        amap = amap.model_copy(update={
            "units": [_named_unit(unit, names) for unit in amap.units],
        })

    alarms = _alarms_from_map(amap)
    conflicts = list(amap.conflicts)
    # E001/E005 here come from unbound seqs/groups (noise on a figure); clean
    # Units may still be published.  Scale/mapping alarms stay hard blockers.
    hard = bool(conflicts) or any(
        str(alarm).startswith("E") and str(alarm) not in ("E001", "E005")
        for alarm in alarms
    )

    figure_number = extract_fig_number(
        fig.caption, fallback=Path(fig.fileref).stem
    )
    writer = cfg.resolved_writer()
    registry = cfg.name_registry if cfg.name_registry is not None else {}
    texts = _text_index(body_artifacts)
    view_map = _views_by_id(views)
    scale_map = _scales_by_id(list(ocr_result.scales))

    image: np.ndarray | None = None
    write_image = not hard
    if write_image:
        try:
            image = load_image(fig.media_path)
        except Exception:  # unreadable image -> no PNG, review, not a crash
            write_image = False

    pairs: list[PairRecord] = []
    ledger: list[dict] = []
    written: dict[tuple, str] = {}
    compose_error: str | None = None
    for unit in amap.units:
        review = hard or unit.status == "review" or unit.artifact_id in blocked
        image_path: str | None = None
        shared = False
        if write_image and image is not None and unit.artifact_id not in blocked:
            # R-IMG-10: identical content + identical bars is one asset; two
            # units holding different bars must not share a PNG.
            key = (tuple(unit.view_ids), bool(unit.whole_image),
                   tuple(b["scale_id"] for b in unit.scale_bindings))
            image_path = written.get(key)
            shared = image_path is not None
            if image_path is None:
                try:
                    canvas, _meta = compose_unit(
                        image, unit, view_map, scale_map
                    )
                except Exception as exc:  # one unit failing is not the batch
                    review = True
                    compose_error = f"compose_failed:{type(exc).__name__}"
                else:
                    candidate = build_image_name(
                        figure_number, _seq_part(unit), unit.artifact_id
                    )
                    image_path = writer.write_image(
                        dedup_name(candidate, registry), canvas
                    )
                    written[key] = image_path

        text = texts.get(unit.artifact_id)
        pair = _build_pair(
            fig=fig, unit=unit, line=WorkLine.MULTI_LINE,
            source_role="line", image_path=str(image_path or ""),
            figure_number=figure_number, text=text, flags=[],
            review=review, shared_image=shared,
        )
        pairs.append(pair)
        ledger.append(_ledger_row(
            fig=fig, unit=unit, line=WorkLine.MULTI_LINE, source_role="line",
            pair=pair, seq=unit.seq_ids[0] if unit.seq_ids else None,
            status=pair.status,
            extra={
                "alarms": alarms, "conflicts": conflicts,
                "unbound": {
                    "groups": amap.unbound_groups,
                    "views": amap.unbound_views,
                    "seqs": amap.unbound_seqs,
                },
                "artifact_map": amap.model_dump(),
            },
        ))
    if compose_error:
        conflicts = _unique(conflicts + [compose_error])

    result = _figure_result(
        fig, ImageType.MULTI_LINE, WorkLine.MULTI_LINE, pairs, amap,
        alarms, conflicts,
    )
    return result, ledger, [
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "figure_input",
         "payload": _figure_payload(fig)},
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "ocr",
         "payload": ocr_result.model_dump()},
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "views",
         "payload": [view.model_dump() for view in views]},
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "text_mapping",
         "payload": text_mapping.model_dump()},
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "bindings",
         "payload": [binding.model_dump() for binding in bindings]},
        {"book_id": fig.book_id, "figure_id": fig.figure_id,
         "kind": "scale_bindings",
         "payload": [_binding_meta(binding, unit)
                     for unit in amap.units
                     for binding in unit.scale_bindings]},
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "artifact_map",
         "payload": amap.model_dump()},
    ]


# --- L2 / L3 / L4 ----------------------------------------------------------


def _resolve_unique_artifact(fig: FigureInput, image_type: ImageType) -> tuple[
    str | None, str | None, TextArtifact | None, list[TextArtifact], list[str]
]:
    """Locate the one artifact id (figure-note > caption > body).

    Indices are built once: with the same body paragraphs repeated for every
    figure of a book, a paragraph-anchored walk would cost O(figures x body).
    """
    note_items = parse_note(fig.figure_note) if fig.figure_note else []
    note_ids = _unique([
        aid for item in note_items for aid in item.artifact_ids
    ] + (extract_artifacts(fig.figure_note) if fig.figure_note else []))
    caption_ids = _unique(extract_caption_artifacts(fig.caption))
    target_ids = set(note_ids) | set(caption_ids)
    text_ids = [
        artifact for artifact in _body_artifact_ids(_relevant_paras(fig, target_ids))
        if artifact.artifact_id in target_ids
    ]
    body_ids = [artifact.artifact_id for artifact in text_ids]
    body = text_ids
    for ids, origin in (
        (note_ids, "figure_note"),
        (caption_ids, "caption"),
        (body_ids, "text"),
    ):
        if len(ids) == 1:
            aid = ids[0]
            text = next((a for a in body if a.artifact_id == aid), None)
            return aid, origin, text, body, []
        if len(ids) > 1:
            return None, origin, None, body, [
                f"multiple_artifacts:{origin}:{','.join(ids)}"
            ]
    return None, None, None, body, []


def _figure_result(
    fig, image_type, line, pairs, amap, alarms, conflicts,
    *, status=None, exclude_reason=None,
) -> FigureResult:
    if status is None:
        status = "output" if pairs else "pending_review"
        if pairs and any(pair.status == "review" for pair in pairs):
            status = "pending_review"
    return FigureResult(
        book_id=fig.book_id,
        figure_id=fig.figure_id,
        image_type=image_type,
        work_line=line,
        status=status,
        pairs=pairs,
        artifact_map=amap,
        alarms=list(alarms),
        conflicts=list(conflicts),
        exclude_reason=exclude_reason,
    )


def _whole_image_unit(artifact_id: str, source: str, case: str | None,
                      line: WorkLine) -> ArtifactUnit:
    return ArtifactUnit(
        artifact_id=artifact_id,
        seq_ids=[],
        view_ids=[],
        group_ids=[],
        scale_bindings=[],
        line=line.value,
        case=case,
        source=source,
        confidence=1.0,
        whole_image=True,
        status="output",
    )


def _l2l3_impl(fig: FigureInput, image_type: ImageType,
               cfg: PipelineConfig) -> tuple:
    line = work_line_of(image_type)
    source_role = "plate" if image_type == ImageType.SINGLE_PLATE else "line"
    case = ("single_plate_artifact" if source_role == "plate"
            else "single_line_artifact")
    aid, source, text, _body, errors = _resolve_unique_artifact(fig, image_type)
    figure_number = extract_fig_number(
        fig.caption, fallback=Path(fig.fileref).stem
    )
    stage: list[dict] = [
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "figure_input",
         "payload": _figure_payload(fig)},
    ]
    if aid is None:
        conflicts = list(errors) or ["no_artifact_id"]
        result = _figure_result(
            fig, image_type, line, [], None, ["E005"], conflicts,
        )
        stage.append({"book_id": fig.book_id, "figure_id": fig.figure_id,
                      "kind": "artifact_map", "payload": None})
        return result, [], stage

    unit = _whole_image_unit(aid, source, case, line)
    note_items = parse_note(fig.figure_note) if fig.figure_note else []
    name = _note_name_for_id(note_items, aid)
    if name:
        unit = unit.model_copy(update={"artifact_name": name})
    writer = cfg.resolved_writer()
    registry = cfg.name_registry if cfg.name_registry is not None else {}
    alarms: list[str] = []
    try:
        image = load_image(fig.media_path)
        canvas, _meta = compose_unit(image, unit, {}, {})
        candidate = build_image_name(figure_number, None, aid)
        candidate = dedup_name(candidate, registry)
        image_path = writer.write_image(candidate, canvas)
    except Exception as exc:
        result = _figure_result(
            fig, image_type, line, [], None, [],
            [f"compose_failed:{type(exc).__name__}"], status="failed",
        )
        return result, [], stage

    pair = _build_pair(
        fig=fig, unit=unit, line=line, source_role=source_role,
        image_path=image_path, figure_number=figure_number, text=text,
        flags=[], review=bool(alarms), shared_image=False,
    )
    ledger_row = _ledger_row(
        fig=fig, unit=unit, line=line, source_role=source_role, pair=pair,
        seq=None, status=pair.status,
        extra={"alarms": alarms, "artifact_map": None},
    )
    status = "output" if pair.status == "output" else "pending_review"
    result = _figure_result(
        fig, image_type, line, [pair], None, alarms, [],
        status=status,
    )
    return result, [ledger_row], stage


def _l4(fig: FigureInput, image_type: ImageType) -> tuple:
    line = work_line_of(image_type)
    reason = {
        ImageType.MULTI_PLATE: "multi_plate_artifact",
        ImageType.DISCARDED: "discarded",
    }.get(image_type, str(image_type.value))
    result = _figure_result(
        fig, image_type, line, [], None, [], [],
        status="excluded", exclude_reason=reason,
    )
    return result, [], [
        {"book_id": fig.book_id, "figure_id": fig.figure_id, "kind": "figure_input",
         "payload": _figure_payload(fig)},
    ]


# --- public entry points ---------------------------------------------------


def _failed(fig: FigureInput, exc: BaseException) -> FigureResult:
    book_id = getattr(fig, "book_id", "") or ""
    figure_id = getattr(fig, "figure_id", "") or ""
    return FigureResult(
        book_id=book_id,
        figure_id=figure_id,
        image_type=ImageType.DISCARDED,
        work_line=WorkLine.ARCHIVE,
        status="failed",
        pairs=[],
        artifact_map=None,
        alarms=[],
        conflicts=[f"pipeline_failed:{type(exc).__name__}"],
        exclude_reason=None,
    )


def process_figure(fig: FigureInput, cfg: PipelineConfig | None = None) -> FigureResult:
    """Run one figure through its work line; never guesses."""
    cfg = cfg or PipelineConfig()
    return _run(fig, cfg)[0]


def process_book(
    figures: list[FigureInput], cfg: PipelineConfig | None = None
) -> list[FigureResult]:
    """Process a whole book; one figure failing never aborts the batch."""
    cfg = cfg or PipelineConfig()
    results: list[FigureResult] = []
    pairs: list[dict] = []
    ledger: list[dict] = []
    for fig in figures:
        try:
            result, rows, stage = _run(fig, cfg)
        except Exception as exc:  # noqa: BLE001 - batch must continue
            result, rows, stage = _failed(fig, exc), [], []
        results.append(result)
        pairs.extend(pair.model_dump() for pair in result.pairs)
        ledger.extend(rows)
        for entry in stage:
            ledger.append(entry)
    writer = cfg.resolved_writer()
    writer.write_pairs(pairs)
    writer.write_ledger(ledger)
    return results


def _run(fig: FigureInput, cfg: PipelineConfig) -> tuple:
    image_type, _line = classify(fig.caption, fig.figure_note, fig.media_path)
    if image_type in (ImageType.MULTI_PLATE, ImageType.DISCARDED):
        return _l4(fig, image_type)
    if image_type == ImageType.MULTI_LINE:
        return _l1(fig, cfg)
    return _l2l3_impl(fig, image_type, cfg)

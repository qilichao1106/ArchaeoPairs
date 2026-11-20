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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
    for item in amap.unbound_views:
        alarms.append("E002")
    return _unique(alarms)


def _dirty(amap: ArtifactMap) -> list[str]:
    """Reasons the mapping cannot be auto-emitted (empty means clean)."""
    reasons: list[str] = []
    if not amap.units:
        reasons.append("no_units")
    if any(str(a).startswith("E") for a in amap.alarms):
        reasons.append("alarms")
    if amap.conflicts:
        reasons.append("conflicts")
    for kind, items in (
        ("unbound_seqs", amap.unbound_seqs),
        ("unbound_groups", amap.unbound_groups),
        ("unbound_views", amap.unbound_views),
    ):
        if items:
            reasons.append(kind)
    return reasons


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


def _filter_aux_views(views: list[View], ocr: OcrResult) -> list[View]:
    """Drop views that are just scale bars or sequence-label glyphs.

    Those regions are owned by OCR and must not become artefact views.  View
    ids are re-indexed contiguously.
    """
    aux = [tuple(s.bbox) for s in ocr.scales] + [tuple(s.bbox) for s in ocr.seqs]
    kept = [v for v in views
            if not any(_aux_owned(tuple(v.bbox), a) for a in aux)]
    return [v.model_copy(update={"view_id": i}) for i, v in enumerate(kept)]


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
    body_artifacts = _body_artifacts(fig.body_paras)
    text_mapping = build_text_mapping(
        note_items, caption_artifacts, body_artifacts
    )
    views = segment_views(fig.media_path)
    ocr_result: OcrResult = ocr.read(fig.media_path)
    if not isinstance(ocr_result, OcrResult):
        raise TypeError(
            f"OCR provider returned {type(ocr_result).__name__}, expected OcrResult"
        )

    views = _filter_aux_views(views, ocr_result)
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
    amap = apply_scale_bindings(amap, bindings_by_group)
    amap = amap.model_copy(update={"alarms": _unique(list(amap.alarms) + list(scale_alarms))})

    alarms = _alarms_from_map(amap)
    conflicts = list(amap.conflicts)
    dirty = _dirty(amap)

    figure_number = extract_fig_number(
        fig.caption, fallback=Path(fig.fileref).stem
    )
    writer = cfg.resolved_writer()
    registry = cfg.name_registry if cfg.name_registry is not None else {}
    texts = _text_index(body_artifacts)
    view_map = _views_by_id(views)
    scale_map = _scales_by_id(list(ocr_result.scales))

    image: np.ndarray | None = None
    write_image = not dirty
    if write_image:
        try:
            image = load_image(fig.media_path)
        except Exception as exc:  # unreadable image -> review, not a crash
            dirty.append(f"image_unreadable:{type(exc).__name__}")
            write_image = False

    pairs: list[PairRecord] = []
    ledger: list[dict] = []
    written: dict[tuple, str] = {}
    compose_error: str | None = None
    for unit in amap.units:
        review = bool(dirty) or unit.status == "review"
        image_path: str | None = None
        shared = False
        if write_image and image is not None:
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
    note_ids = _unique([
        aid
        for item in (parse_note(fig.figure_note) if fig.figure_note else [])
        for aid in item.artifact_ids
    ])
    caption_ids = _unique(extract_caption_artifacts(fig.caption))
    text_ids = _body_artifact_ids(fig.body_paras)
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

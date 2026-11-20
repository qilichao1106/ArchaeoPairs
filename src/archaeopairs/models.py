"""Core data models for the ArchaeoPairs pipeline (T-002, T-003, T-004).

Five-way image classification and the mapping onto the four work lines
(``multi_line`` / ``single_line`` / ``single_plate`` / ``archive``) per
requirements V1.0 R-IN-11, plus the OCR result models consumed by the
pluggable OCR providers (AC-03).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# An OCR bounding box is always ``[x0, y0, x1, y1]`` in image pixels.
BBox = tuple[int, int, int, int]


class ImageType(str, Enum):
    """Five-way image classification (R-IN-11)."""

    SINGLE_LINE = "single_line_artifact"
    MULTI_LINE = "multi_line_artifact"
    SINGLE_PLATE = "single_plate_artifact"
    MULTI_PLATE = "multi_plate_artifact"
    DISCARDED = "discarded"


class WorkLine(str, Enum):
    """Four work lines (R-L1..R-L4). Values match the frozen schemas."""

    MULTI_LINE = "multi_line"
    SINGLE_LINE = "single_line"
    SINGLE_PLATE = "single_plate"
    ARCHIVE = "archive"


class FigureInput(BaseModel):
    """A single figure parsed from ``books/<book>/data.xml`` plus its body.

    ``book_id`` namespaces every downstream identifier (R-IN-08). ``caption``
    and ``figure_note`` may legitimately be ``None`` (R-IN-04): caller must not
    guess missing titles/notes.
    """

    book_id: str
    figure_id: str
    fileref: str
    media_path: str
    caption: str | None = None
    figure_note: str | None = None
    body_paras: list[dict] = Field(default_factory=list)


class NoteItem(BaseModel):
    """One figure-note clause: a seq fragment plus its artifact ids (T-003)."""

    seq: str
    seq_list: list[int] = Field(default_factory=list)
    name: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)


class TextArtifact(BaseModel):
    """Body text attributed to one artifact id (R-OUT-03, T-003).

    ``markers`` records how the segment was anchored: ``single_anchor`` /
    ``multi_anchor`` for directly anchored text, ``no_anchor`` for text hung
    off the nearest preceding anchor.
    """

    artifact_id: str
    text: str
    source_para_ids: list[str] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)


class TextMapping(BaseModel):
    """seq -> artifact mapping for one figure (R-MAP-01..07, T-003)."""

    seq_to_artifacts: dict[str, list[str]] = Field(default_factory=dict)
    caption_artifacts: list[str] = Field(default_factory=list)
    case_type: str
    conflicts: list[str] = Field(default_factory=list)


class SeqLabel(BaseModel):
    """A sequence number printed beside/drawn on an artifact (T-004, AC-03)."""

    text: str
    bbox: BBox
    conf: float | None = None


class ScaleBar(BaseModel):
    """A scale bar reading, optionally shared by several artifact numbers."""

    text: str
    bbox: BBox
    value: float | None = None
    unit: str | None = None
    prefix_nos: list[str] = Field(default_factory=list)


class ScaleBinding(BaseModel):
    """One scale bar bound to a view group / unit (T-008, R-SCALE-01..05).

    ``source`` records the binding tier: ``L1_prefix`` (bar prefix numbers
    intersect the group's seqs), ``L2_unique_shared`` (the figure has exactly
    one bar, copied to every unit), ``L3_vl`` (reserved for a future VLM
    prefix reader) or ``unknown``.  ``shared`` marks copies of one bar handed
    to several units.  No field is ever derived from pixel distance.
    """

    scale_id: int
    source: str = "unknown"  # L1_prefix | L2_unique_shared | L3_vl | unknown
    shared: bool = False
    text: str = ""
    value: float | None = None
    unit: str | None = None
    prefix_nos: list[str] = Field(default_factory=list)


class TextBlock(BaseModel):
    """Any other printed text block (title, annotation, note fragment)."""

    text: str
    bbox: BBox


class OcrResult(BaseModel):
    """Structured OCR output for one figure image.

    ``source`` is ``vlm`` / ``paddle`` for a single provider or ``hybrid``
    after :func:`archaeopairs.ocr.base.merge_ocr_results`.  ``raw`` keeps the
    provider payload (or merged provenance such as ``raw["conflicts"]``).
    """

    seqs: list[SeqLabel] = Field(default_factory=list)
    scales: list[ScaleBar] = Field(default_factory=list)
    texts: list[TextBlock] = Field(default_factory=list)
    source: str = "unknown"  # vlm | paddle | hybrid
    raw: dict[str, Any] = Field(default_factory=dict)

class View(BaseModel):
    """One pixel-level view (an atomic connected line-drawing region) (T-006).

    ``bbox`` is ``(x0, y0, x1, y1)`` in image pixels with the right/bottom
    edges exclusive; ``mask_rle`` is a COCO-style column-major RLE string
    (see :mod:`archaeopairs.vision.rle`) covering the *full* image, not just
    the bbox.  ``incomplete`` flags a mask known to be cut (e.g. shared
    baseline, E006); segmentation itself always emits ``False``.
    """

    view_id: int
    bbox: BBox
    area: int
    mask_rle: str
    incomplete: bool = False

# --- View binding / grouping / ArtifactMap (T-007) -------------------------


class ViewBinding(BaseModel):
    """One seq label bound to the view that spatially contains it (T-007).

    ``method`` records how the binding was found: ``inside`` / ``smallest_containing``
    for an unambiguous / multi-candidate bbox hit, ``unbound`` when no view
    bbox contains the label centre (never distance-guessed).
    """

    view_id: int
    seq_id: str | None
    method: str = "inside"  # inside | smallest_containing | unbound
    confidence: float = 1.0


class ViewGroup(BaseModel):
    """All views sharing one ``seq_id`` (or the whole figure under rule B)."""

    group_id: int
    view_ids: list[int] = Field(default_factory=list)
    seq_ids: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)


class ArtifactUnit(BaseModel):
    """One artifact id with the seqs/views/groups that resolve to it (T-007)."""

    artifact_id: str
    artifact_name: str | None = None
    seq_ids: list[str] = Field(default_factory=list)
    view_ids: list[int] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    scale_bindings: list[dict] = Field(default_factory=list)  # ScaleBinding dumps (T-008)
    line: str = "multi_line"
    case: str | None = None
    source: str = "figure_note"
    confidence: float = 0.0
    whole_image: bool = False
    status: str = "output"
    evidence: dict = Field(default_factory=dict)


class ArtifactMap(BaseModel):
    """Per-figure ledger of artifact units plus unbound items/conflicts."""

    book_id: str
    figure_id: str
    line: str = "multi_line"
    case_type: str | None = None
    units: list[ArtifactUnit] = Field(default_factory=list)
    unbound_groups: list[dict] = Field(default_factory=list)
    unbound_views: list[dict] = Field(default_factory=list)
    unbound_seqs: list[dict] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    alarms: list[str] = Field(default_factory=list)
    status: str = "composed"


# --- PairRecord / FigureResult (T-010) -------------------------------------

QualityFlag = Literal[
    "no_text", "no_scale", "long_text", "degraded", "multi_panel", "shared_image"
]
SourceRole = Literal["line", "plate"]
PairStatus = Literal["output", "review", "archived"]
FigureStatus = Literal["output", "pending_review", "excluded", "failed"]


class MappingRef(BaseModel):
    """``provenance.mapping`` of one Pair (R-OUT-06, pair_record.schema.json)."""

    artifact_id: str
    seq_ids: list[str] = Field(default_factory=list)
    view_ids: list[int] = Field(default_factory=list)
    scale_ids: list[int] = Field(default_factory=list)
    scale_sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    line: WorkLine = WorkLine.MULTI_LINE
    source_role: SourceRole = "line"


class CandidateImage(BaseModel):
    """One candidate image for a Pair (line / plate / fallback candidate)."""

    path: str
    role: Literal["line", "plate", "candidate"] = "candidate"
    source_figure_id: str | None = None
    confidence: float | None = None


class Provenance(BaseModel):
    """Audit trail of a Pair; ``mapping`` is the frozen required member."""

    mapping: MappingRef
    source_para_ids: list[str] = Field(default_factory=list)
    art_source: Literal["figure_note", "caption", "text", "manual"] | None = None
    case: str | None = None
    shared_group: str | None = None


class PairRecord(BaseModel):
    """One artifact image_pair row (requirements R-OUT-01..08).

    Frozen schema 1.0 has exactly one review value (``review``); the pipeline
    stage vocabulary (``pending_review`` / ``failed``) lives on
    :class:`FigureResult` and in the ledger, never on a Pair.
    """

    book_id: str
    figure_id: str
    artifact_id: str
    artifact_name: str | None = None
    figure_number: str | None = None
    source_role: SourceRole = "line"
    image_path: str
    candidate_images: list[CandidateImage] = Field(default_factory=list)
    image_merge_mode: Literal[
        "line_only", "plate_only", "line_plus_plate", "multi_candidate"
    ] = "line_only"
    description_text: str | None = None
    text_length: int = Field(default=0, ge=0)
    provenance: Provenance
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    status: PairStatus = "output"
    schema_version: Literal["1.0"] = "1.0"


class FigureResult(BaseModel):
    """Outcome of :func:`archaeopairs.pipeline.process_figure` for one figure.

    ``status`` is ``output`` (pairs emitted), ``pending_review`` (no pairs, or
    pairs hold back for review), ``excluded`` (L4 archive, zero pairs) or
    ``failed`` (exception; the batch continues).
    """

    book_id: str
    figure_id: str
    image_type: ImageType
    work_line: WorkLine
    status: FigureStatus = "pending_review"
    pairs: list[PairRecord] = Field(default_factory=list)
    artifact_map: ArtifactMap | None = None
    alarms: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exclude_reason: str | None = None

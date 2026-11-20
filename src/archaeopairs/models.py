"""Core data models for the ArchaeoPairs pipeline (T-002, T-003).

Five-way image classification and the mapping onto the four work lines
(``multi_line`` / ``single_line`` / ``single_plate`` / ``archive``) per
requirements V1.0 R-IN-11.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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

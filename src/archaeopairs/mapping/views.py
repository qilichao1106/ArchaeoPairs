"""Seq-label binding, view grouping and ArtifactMap assembly (T-007).

Flow for one figure::

    seq label bbox centre -> containing view (smallest area) -> ViewBinding
    views with the same seq_id -> ViewGroup
    ViewGroup + TextMapping -> ArtifactUnit(s) -> ArtifactMap

Binding is strictly spatial: a label binds to the smallest view bbox that
contains its centre.  A label whose centre is in no view is ``unbound`` --
never placed by nearest-distance guessing (R-SEQ-02/R-SEQ-03).  Which
*artifact* a seq belongs to is decided only by :class:`TextMapping`.

Cardinalities follow R-MAP-02/03/06/07::

* 1 seq : N art -> N units sharing the group's views (``split_same_seq``);
* N seq : 1 art -> one unit for all the group's views (``rule_b``);
* N seq : N art -> one unit per artifact over the whole group's views;
* same artifact in several groups merges only when every group declares just
  that one artifact; otherwise ``cross_group_artifact:<id>`` conflict.

Scale binding is intentionally out of scope here (T-008): every unit keeps
``scale_bindings=[]``.
"""

from __future__ import annotations

import re

from archaeopairs.models import (
    ArtifactMap,
    ArtifactUnit,
    SeqLabel,
    TextMapping,
    View,
    ViewBinding,
    ViewGroup,
)

INSIDE = "inside"
SMALLEST_CONTAINING = "smallest_containing"
NEAREST = "nearest"
UNBOUND = "unbound"

# Confidence per binding method / unit source (R-MAP-01, R-MAP-04).
_METHOD_CONFIDENCE = {INSIDE: 1.0, SMALLEST_CONTAINING: 0.9, NEAREST: 0.7}
_CAPTION_FALLBACK_CONFIDENCE = 0.8  # 图题 弱链, confidence x0.8
_SAME_SEQ_SHARED_CONFIDENCE = 0.8   # 1 seq : N art -> one shared image asset

_CIRCLED = {chr(0x2460 + i): str(i + 1) for i in range(9)}  # ①..⑨
_CIRCLED["⑩"] = "10"
_SEQ_LABEL = re.compile(r"\s*(\d+|[A-Za-z])\s*[.．、]?\s*")


def normalize_seq_label(text: str) -> str | None:
    """Normalize one printed seq label to its bare id, or ``None``.

    ``"1."`` / ``"1、"`` / ``"1"`` / ``"①"`` -> ``"1"``; ``"A."`` -> ``"A"``.
    Group/range labels (``"2、3"``, ``"1～4"``, ``"1,2"``) are *not* a single
    seq and return ``None`` -- they are handled by the group-label parser.
    """
    if text is None:
        return None
    value = text.strip()
    if not value:
        return None
    if len(value) == 1 and value in _CIRCLED:
        return _CIRCLED[value]
    if any(mark in value for mark in ("，", ",", "~", "～", "∼", "-", "–")):
        return None
    # A single trailing 顿号 is a separator (``1、``); a 顿号 between two
    # tokens is a group label (``1、2``) -> not one seq.
    if value.endswith("、"):
        value = value[:-1].strip()
    if "、" in value:
        return None
    match = _SEQ_LABEL.fullmatch(value)
    return match.group(1) if match else None


def _centre(bbox) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _area(box) -> int:
    x0, y0, x1, y1 = box
    return max(0, x1 - x0) * max(0, y1 - y0)


def _gap(a: tuple, b: tuple) -> float:
    """Euclidean distance between two bboxes (0 when they touch/overlap)."""
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return float((dx * dx + dy * dy) ** 0.5)


def _is_label_glyph(view_box: tuple, label_box: tuple,
                    gap_max: float = 12.0) -> bool:
    """A small view next to the label is the label glyph, not a drawing.

    OCR bboxes are routinely a few pixels off the printed glyph, so an
    overlap-only test leaves the digit as a drawing candidate; that candidate
    then wins the nearest-view race against the real drawing.  Size + area
    ratio + a small gap tolerance identifies the glyph while a genuinely small
    drawing (area > 4x the label) stays eligible.
    """
    # A printed seq label is small; wide OCR boxes are group spans, not glyphs.
    if (label_box[2] - label_box[0] > 60
            or label_box[3] - label_box[1] > 60
            or view_box[2] - view_box[0] > 60
            or view_box[3] - view_box[1] > 60):
        return False
    view_area = _area(view_box)
    label_area = _area(label_box)
    if label_area <= 0 or view_area <= 0 or view_area > 4 * label_area:
        return False
    inter = (max(0, min(view_box[2], label_box[2]) - max(view_box[0], label_box[0]))
             * max(0, min(view_box[3], label_box[3]) - max(view_box[1], label_box[1])))
    return inter > 0 or _gap(view_box, label_box) <= gap_max


def bind_labels_to_views(
    views: list[View], seq_labels: list[SeqLabel], *,
    label_gap_max: float = 60.0,
) -> list[ViewBinding]:
    """Bind each label to its view: centre containment first, then a near gap.

    Printed sequence labels usually sit just below/left of the drawing, so a
    centre-only rule misses them.  When no view contains the centre, the label
    binds to the single nearest view within ``label_gap_max``; a tie is left
    ``unbound`` (never guessed).  This is only for attaching the label glyph to
    its drawing; artifact/scale matching never uses distance (R-SEQ-02).
    """
    ordered = sorted(views, key=lambda view: view.view_id)
    bindings: list[ViewBinding] = []
    for label in seq_labels or []:
        seq_id = normalize_seq_label(label.text)
        if seq_id is None:
            continue
        cx, cy = _centre(label.bbox)
        candidates = [view for view in ordered
                      if not _is_label_glyph(tuple(view.bbox), tuple(label.bbox))]
        containing = [
            view for view in candidates
            if view.bbox[0] <= cx <= view.bbox[2]
            and view.bbox[1] <= cy <= view.bbox[3]
        ]
        if containing:
            method = INSIDE if len(containing) == 1 else SMALLEST_CONTAINING
            target = min(containing, key=lambda v: (_area(v.bbox), v.bbox, v.view_id))
        else:
            nearby = [(g, view) for view in candidates
                      for g in [_gap(label.bbox, view.bbox)]
                      if g <= label_gap_max]
            if not nearby:
                bindings.append(ViewBinding(
                    view_id=-1, seq_id=seq_id, method=UNBOUND, confidence=0.0))
                continue
            best = min(g for g, _view in nearby)
            ties = [view for g, view in nearby if abs(g - best) <= 1e-6]
            if len(ties) != 1:
                bindings.append(ViewBinding(
                    view_id=-1, seq_id=seq_id, method=UNBOUND, confidence=0.0))
                continue
            method = NEAREST
            target = ties[0]
        bindings.append(ViewBinding(
            view_id=target.view_id, seq_id=seq_id, method=method,
            confidence=_METHOD_CONFIDENCE[method]))
    return bindings


def _unique(items) -> list:
    seen: set = set()
    out: list = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def group_views(
    views: list[View],
    bindings: list[ViewBinding],
    *,
    all_unlabeled_rule_b: bool = False,
) -> tuple[list[ViewGroup], list[dict]]:
    """Group views sharing a ``seq_id``; report views with no binding.

    Groups are numbered ``0..`` in first-seen reading order (seqs taken in
    input order, then by ``view_id``); ``view_ids`` follow input order.  With
    ``all_unlabeled_rule_b`` and no label bound anywhere, every view forms one
    group with ``seq_ids=[]`` (a single whole-image artifact, R-MAP-08).
    """
    order = {view.view_id: index for index, view in enumerate(views)}
    bound: dict[str, list[int]] = {}
    for binding in bindings or []:
        if binding.seq_id is None or binding.view_id not in order:
            continue
        ids = bound.setdefault(binding.seq_id, [])
        if binding.view_id not in ids:
            ids.append(binding.view_id)

    if not bound and all_unlabeled_rule_b and views:
        group = ViewGroup(
            group_id=0,
            view_ids=[view.view_id for view in views],
            seq_ids=[],
            evidence={"rule": "all_unlabeled_rule_b", "has_labels": False},
        )
        return [group], []

    groups: list[ViewGroup] = []
    for seq_id, view_ids in bound.items():
        groups.append(ViewGroup(
            group_id=len(groups),
            view_ids=sorted(view_ids, key=lambda vid: order[vid]),
            seq_ids=[seq_id],
            evidence={"has_labels": True},
        ))
    used = {vid for ids in bound.values() for vid in ids}
    unbound = [
        {"view_ids": [view.view_id], "reason": "no_seq"}
        for view in views if view.view_id not in used
    ]
    return groups, unbound


def _dedupe_conflicts(conflicts: list[str]) -> list[str]:
    return _unique(conflicts)


def build_artifact_map(
    views: list[View],
    bindings: list[ViewBinding],
    text_mapping: TextMapping,
    *,
    book_id: str,
    figure_id: str,
    line: str = "multi_line",
    all_unlabeled_rule_b: bool = False,
) -> ArtifactMap:
    """Assemble an :class:`ArtifactMap` from views, bindings and text mapping."""
    groups, unbound_views = group_views(
        views, bindings, all_unlabeled_rule_b=all_unlabeled_rule_b
    )
    seq_to_artifacts = text_mapping.seq_to_artifacts or {}
    conflicts = list(text_mapping.conflicts or [])
    unbound_groups: list[dict] = []

    # Per group: the artifact ids it declares (deduped, note order) and whether
    # that is the shared single artifact of an N seq : 1 art rule-B group.
    declared: dict[int, list[str]] = {}
    whole_image_groups: set[int] = set()
    for group in groups:
        if not group.seq_ids:
            continue
        arts = _unique(a for seq in group.seq_ids
                       for a in seq_to_artifacts.get(seq, []))
        if not arts:
            unbound_groups.append({
                "group_id": group.group_id,
                "view_ids": list(group.view_ids),
                "seq_id": group.seq_ids[0] if len(group.seq_ids) == 1 else None,
                "reason": "unmapped_seq",
            })
            continue
        declared[group.group_id] = arts
        if len(group.seq_ids) > 1 and len(arts) == 1:
            whole_image_groups.add(group.group_id)

    # Cross-group ownership (R-MAP-06): an artifact may span several groups
    # only when every group that holds it declares just that one artifact;
    # otherwise it is a conflict and each group keeps its own unit.
    holders: dict[str, list[int]] = {}
    for group_id, arts in declared.items():
        for artifact in arts:
            holders.setdefault(artifact, []).append(group_id)
    cross_group = {
        artifact for artifact, group_ids in holders.items()
        if len(group_ids) > 1
        and not all(declared[gid] == [artifact] for gid in group_ids)
    }
    for artifact in sorted(cross_group):
        conflicts.append(f"cross_group_artifact:{artifact}")

    all_view_ids = sorted(view.view_id for view in views)

    units: list[ArtifactUnit] = []
    merged: dict[str, ArtifactUnit] = {}
    for group in groups:
        group_id = group.group_id
        view_ids = list(group.view_ids)
        seq_ids = list(group.seq_ids)

        if not seq_ids:  # rule B: whole figure, no seq id at all
            captions = _unique(text_mapping.caption_artifacts or [])
            if not captions:
                unbound_groups.append({
                    "group_id": group_id, "view_ids": view_ids,
                    "seq_id": None, "reason": "no_seq",
                })
                continue
            if len(captions) > 1:
                conflicts.append(
                    "caption_multi_artifact:" + ",".join(captions))
                continue
            units.append(ArtifactUnit(
                artifact_id=captions[0], seq_ids=[], view_ids=view_ids,
                group_ids=[group_id], line=line, case="rule_b",
                source="caption", confidence=_CAPTION_FALLBACK_CONFIDENCE,
                whole_image=view_ids == all_view_ids,
                evidence={"rule": "all_unlabeled_rule_b"},
            ))
            continue

        arts = declared.get(group_id, [])
        # A lone artifact covering the whole group is one combined drawing:
        # rule B when the group spans several seqs, otherwise a single unit.
        combined = len(arts) == 1 and view_ids == all_view_ids
        case = "rule_b" if group_id in whole_image_groups else (
            "split_same_seq" if len(seq_ids) == 1 and len(arts) > 1 else None)
        for artifact in arts:
            if artifact in cross_group:
                # Unmerged, one unit per group, for review (R-MAP-06).
                units.append(ArtifactUnit(
                    artifact_id=artifact, seq_ids=seq_ids, view_ids=view_ids,
                    group_ids=[group_id], line=line, case=case,
                    confidence=0.0, whole_image=combined, status="review",
                    evidence={"cross_group_artifact": True},
                ))
                continue
            if len(holders.get(artifact, [])) > 1:
                # Each holder declares only this artifact -> one merged unit.
                unit = merged.get(artifact)
                if unit is None:
                    unit = ArtifactUnit(
                        artifact_id=artifact, line=line,
                        case="rule_b" if group_id in whole_image_groups
                        or len(seq_ids) > 1 else None,
                        confidence=1.0, evidence={"merged_groups": True},
                    )
                    merged[artifact] = unit
                    units.append(unit)
                _extend(unit.seq_ids, seq_ids)
                _extend(unit.view_ids, view_ids)
                _extend(unit.group_ids, [group_id])
                unit.whole_image = unit.view_ids == all_view_ids
                if group_id in whole_image_groups or len(unit.seq_ids) > 1:
                    unit.case = "rule_b"
                continue
            if len(seq_ids) == 1 and len(arts) > 1:
                confidence, evidence = _SAME_SEQ_SHARED_CONFIDENCE, {
                    "shared_group": True, "artifact_count": len(arts)}
            else:
                confidence, evidence = 1.0, {}
            units.append(ArtifactUnit(
                artifact_id=artifact, seq_ids=seq_ids, view_ids=view_ids,
                group_ids=[group_id], line=line, case=case,
                confidence=confidence, whole_image=combined, evidence=evidence,
            ))
    # seqs declared by the note that no group resolved to a unit (E001 signal).
    emitted_seqs = {seq for unit in units for seq in unit.seq_ids}
    group_seqs = {seq for group in groups for seq in group.seq_ids}
    unbound_map: dict[str, dict] = {}
    for seq in _unique(seq_to_artifacts):
        if seq not in emitted_seqs and seq not in group_seqs:
            unbound_map[seq] = {
                "seq_id": seq, "reason": "no_view",
                "artifact_ids": list(seq_to_artifacts[seq]),
            }
    # OCR labels that fell outside every view are E001 signals too.
    for binding in bindings:
        seq = binding.seq_id
        if seq and binding.method == "unbound" and seq not in emitted_seqs:
            unbound_map.setdefault(seq, {
                "seq_id": seq, "reason": "no_view",
                "artifact_ids": list(seq_to_artifacts.get(seq, [])),
            })
    unbound_seqs = list(unbound_map.values())

    conflicts = _dedupe_conflicts(conflicts)
    alarms: list[str] = []  # E001/E005/E006 are appended by the upper layer
    # E001/E005 are raised by the upper layer; here only structural status.
    failed = not units or bool(conflicts) or bool(alarms)
    status = "pending_review" if failed else "composed"
    return ArtifactMap(
        book_id=book_id,
        figure_id=figure_id,
        line=line,
        case_type=text_mapping.case_type,
        units=units,
        unbound_groups=unbound_groups,
        unbound_views=unbound_views,
        unbound_seqs=unbound_seqs,
        conflicts=conflicts,
        alarms=alarms,
        status=status,
    )


def _extend(target: list, values) -> None:
    for value in values:
        if value not in target:
            target.append(value)

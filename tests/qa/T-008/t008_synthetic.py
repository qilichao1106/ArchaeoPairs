"""Synthetic builders for the frozen T-008 tests.

No image pixels, files or network are involved; every object is built from
plain in-memory values so a failure points at the binding logic, not at I/O.
"""

from __future__ import annotations

from archaeopairs.models import ArtifactMap, ArtifactUnit, ScaleBar, ViewGroup


def make_group(group_id: int, seq_ids=(), view_ids=None) -> ViewGroup:
    """One ViewGroup; ``seq_ids`` are normalised to the strings bind_scales sees."""
    if view_ids is None:
        view_ids = [group_id]
    return ViewGroup(
        group_id=group_id,
        view_ids=[int(view_id) for view_id in view_ids],
        seq_ids=[str(seq_id) for seq_id in seq_ids],
    )


def make_scale(
    text: str = "",
    prefix_nos=(),
    bbox=(0, 0, 40, 8),
    value: float | None = None,
    unit: str | None = "cm",
) -> ScaleBar:
    """One synthetic ScaleBar with an explicit (never inferred) prefix list."""
    return ScaleBar(
        text=text,
        bbox=tuple(bbox),
        value=value,
        unit=unit,
        prefix_nos=[str(no) for no in prefix_nos],
    )


def make_unit(
    artifact_id: str,
    group_ids,
    *,
    status: str = "output",
    seq_ids=(),
    view_ids=None,
) -> ArtifactUnit:
    """One ArtifactUnit pointing at ``group_ids`` (which may exceed the groups)."""
    if view_ids is None:
        view_ids = group_ids
    return ArtifactUnit(
        artifact_id=artifact_id,
        seq_ids=[str(seq_id) for seq_id in seq_ids],
        view_ids=[int(view_id) for view_id in view_ids],
        group_ids=[int(group_id) for group_id in group_ids],
        status=status,
    )


def make_map(units=(), *, conflicts=(), alarms=()) -> ArtifactMap:
    """One synthetic ArtifactMap; input lists are copied, never shared."""
    return ArtifactMap(
        book_id="synthetic-book",
        figure_id="fig-synthetic-1",
        units=list(units),
        conflicts=list(conflicts),
        alarms=list(alarms),
    )


def sources(bindings) -> list[str]:
    """Binding sources in returned order, for compact assertions."""
    return [binding.source for binding in bindings]


def scale_ids(bindings) -> list[int]:
    """Binding scale ids in returned order, for compact assertions."""
    return [binding.scale_id for binding in bindings]
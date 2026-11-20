"""Three-tier scale-bar binding (T-008, R-SCALE-01..05).

Tiers, in strict priority order (never by pixel distance)::

    L1  尺的 prefix_nos 与 ViewGroup.seq_ids 有交集 -> 硬绑该组 (L1_prefix)
    L2  全图恰好 1 把尺且无任何 L1 绑定 -> 复制给所有组 (L2_unique_shared)
    L3  >=2 把尺且某尺无 prefix_nos -> 该尺不绑定, 报警 E004 (禁止坐标推断)

Any group left without a bar raises E007 and records ``group_no_scale:<id>``
in the returned alarms.  :func:`apply_scale_bindings` copies the result onto
units by ``group_ids`` union (de-duplicated by ``scale_id``) and sends
bar-less units to review without mutating the input map.

L3 in this card is the *failure* path only: a future VLM prefix reader may
feed read prefixes back in, producing ``source="L3_vl"`` bindings.
"""

from __future__ import annotations

from typing import Iterable

from archaeopairs.models import (
    ArtifactMap,
    ScaleBar,
    ScaleBinding,
    ViewGroup,
)

L1_PREFIX = "L1_prefix"
L2_SHARED = "L2_unique_shared"
E004 = "E004"
E007 = "E007"

_REVIEW = "review"
_PENDING = "pending_review"

_BindingKey = tuple[int, int]  # (group index, scale index)


def _unique(values: Iterable) -> list:
    seen: set = set()
    out: list = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _prefixes(scale: ScaleBar) -> list[str]:
    """Normalised, de-duplicated, order-preserving prefix numbers."""
    return _unique(str(no).strip() for no in (scale.prefix_nos or [])
                   if str(no).strip())


def _binding(scale_id: int, scale: ScaleBar, *, source: str,
             shared: bool) -> ScaleBinding:
    return ScaleBinding(
        scale_id=scale_id,
        source=source,
        shared=shared,
        text=scale.text or "",
        value=scale.value,
        unit=scale.unit,
        prefix_nos=_prefixes(scale),
    )


def _record(index: int, scale: ScaleBar) -> dict:
    return {
        "scale_id": index,
        "text": scale.text or "",
        "bbox": list(scale.bbox) if scale.bbox is not None else None,
        "value": scale.value,
        "unit": scale.unit,
        "prefix_nos": _prefixes(scale),
        "abandoned": False,
        "source": None,
    }


def bind_scales(groups: list[ViewGroup], scales: list[ScaleBar]) -> tuple[
    list[list[ScaleBinding]], list[dict], list[str]
]:
    """Bind each scale bar to groups; return (per-group bindings, records, alarms).

    ``bindings_by_group[i]`` belongs to ``groups[i]`` and may be empty when
    that group has no bar (E007 + ``group_no_scale:<group_id>``).  ``records``
    has one entry per bar; ``alarms`` holds E-codes and ``group_no_scale``
    evidence strings.  Bars are never assigned by bbox distance; an unnumbered
    bar among several bars is abandoned (E004) and recorded as such.
    """
    groups = list(groups or [])
    scales = list(scales or [])
    records = [_record(index, scale) for index, scale in enumerate(scales)]
    prefixes = [_prefixes(scale) for scale in scales]
    # (group index, scale index) -> (binding, shared) in priority order.
    found: dict[_BindingKey, tuple[ScaleBinding, bool]] = {}

    # L1: prefix intersection with the group's seqs is a hard binding.
    for si, nos in enumerate(prefixes):
        if not nos:
            continue
        wanted = set(nos)
        for gi, group in enumerate(groups):
            seq_ids = {str(seq) for seq in (group.seq_ids or [])}
            if not wanted.intersection(seq_ids):
                continue
            shared = len(nos) > 1 or len(seq_ids) > 1
            found[(gi, si)] = (_binding(
                si, scales[si], source=L1_PREFIX, shared=shared), shared)

    # L2: exactly one bar on the figure and no L1 binding -> share it.
    if len(scales) == 1 and not found:
        for gi, group in enumerate(groups):
            found[(gi, 0)] = (_binding(
                0, scales[0], source=L2_SHARED, shared=True), True)

    for (gi, si), (binding, shared) in found.items():
        records[si]["source"] = records[si]["source"] or binding.source
        records[si]["shared"] = bool(records[si].get("shared")) or shared

    # L3 failure path: >=2 bars, some unnumbered -> abandon it (E004).
    alarms: list[str] = []
    if len(scales) >= 2:
        for si, nos in enumerate(prefixes):
            if nos:
                continue
            records[si]["abandoned"] = True
            records[si]["source"] = None
            if E004 not in alarms:
                alarms.append(E004)

    # Groups still without a bar must not be silent (E007).
    bindings_by_group: list[list[ScaleBinding]] = [[] for _ in groups]
    for gi in range(len(groups)):
        for key in sorted(k for k in found if k[0] == gi):
            bindings_by_group[gi].append(found[key][0])
        if not bindings_by_group[gi]:
            alarms.append(f"group_no_scale:{groups[gi].group_id}")
            if E007 not in alarms:
                alarms.append(E007)

    return bindings_by_group, records, _unique(alarms)

def apply_scale_bindings(amap: ArtifactMap,
                         bindings_by_group: list[list[ScaleBinding]]) -> ArtifactMap:
    """Return a copy of ``amap`` with scale bindings applied per unit.

    Each unit collects the bindings of every group in its ``group_ids``
    (union, de-duplicated by ``scale_id``; first occurrence wins).  A unit
    with no bar becomes ``status="review"`` and adds
    ``group_no_scale:<group_id>`` for each of its groups; it is never
    dropped.  ``amap`` itself is not modified; alarms/conflicts already on
    the input are kept, so E004/E007 from :func:`bind_scales` should be
    written onto ``amap`` (or reported) by the caller before applying.
    """
    result = amap.model_copy(deep=True)
    extra_conflicts: list[str] = []
    changed = False
    for unit in result.units:
        collected: list[ScaleBinding] = []
        seen: set[int] = set()
        for group_id in _unique(unit.group_ids or []):
            index = int(group_id)
            if not 0 <= index < len(bindings_by_group):
                continue
            for binding in bindings_by_group[index] or []:
                if binding.scale_id in seen:
                    continue
                seen.add(binding.scale_id)
                collected.append(binding)
        unit.scale_bindings = [binding.model_dump() for binding in collected]
        if collected:
            continue
        unit.status = _REVIEW
        changed = True
        for group_id in _unique(unit.group_ids or []):
            extra_conflicts.append(f"group_no_scale:{group_id}")
    result.conflicts = _unique(list(result.conflicts) + extra_conflicts)
    if changed or extra_conflicts:
        result.status = _PENDING
    return result
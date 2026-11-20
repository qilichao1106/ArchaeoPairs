"""Figure-note / caption -> seq to artifact-id mapping (R-MAP-01..07).

Priority is figure note > caption (weak) > body. ``build_text_mapping`` builds
the mapping for one figure and records the cardinality that produced it:

* 1 seq : N art -> every artifact hangs on that seq (``split_same_seq``);
* N seq : 1 art -> the artifact hangs on every seq (``rule_b``);
* N seq : N art -> positional zip, ``rule_a`` unless the seq is a range
   (``1～4``) -> ``range_split``;
* mismatched counts, or an artifact claimed by two seqs -> ``conflicts`` and
  no guessing (R-MAP-03); no ids at all -> ``seq_missing`` (degraded).

Keys are per declared seq: ``1、2. 陶豆（M4:2、M4:1）`` becomes ``1 -> M4:2``
and ``2 -> M4:1``, never a ``"1,2"`` key.  Artifacts never form a Cartesian
product; body-only artifacts are not run through the cardinality rules.
"""

from __future__ import annotations

from archaeopairs.models import NoteItem, TextArtifact, TextMapping

RULE_A = "rule_a"
RULE_B = "rule_b"
SPLIT_SAME_SEQ = "split_same_seq"
RANGE_SPLIT = "range_split"
SEQ_MISSING = "seq_missing"


def _seq_keys(item: NoteItem) -> list[str]:
    """One key per declared seq (``4、6、7`` -> ``4`` / ``6`` / ``7``)."""

    if item.seq_list:
        return [str(n) for n in item.seq_list]
    seq = item.seq.strip()
    return [seq] if seq else []


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _is_range(item: NoteItem) -> bool:
    """True when the clause seq is a range (``1~4`` / ``1～4``)."""

    return "~" in item.seq or "～" in item.seq


def build_text_mapping(
    note_items: list[NoteItem],
    caption_artifacts: list[str],
    text_artifacts: list[TextArtifact] | None = None,
) -> TextMapping:
    """Map note seqs to artifact ids, falling back to the caption title.

    Every declared seq becomes its own key.  The note is authoritative for
    artifacts: ``caption_artifacts`` is only consulted when a note clause has
    seqs but no artifact ids at all.  Count mismatches and artifacts claimed
    by different seqs are reported in ``conflicts`` and never guessed.
    """

    conflicts: list[str] = []
    mapping: dict[str, list[str]] = {}
    owner: dict[str, str] = {}
    cases: list[str] = []

    items = list(note_items or [])
    note_has_ids = any(item.artifact_ids for item in items)

    if items and note_has_ids:
        for item in items:
            keys = _seq_keys(item)
            if not keys:
                continue
            ids = list(item.artifact_ids)
            if not ids:
                continue
            n_seq, n_art = len(keys), len(ids)

            if n_seq > 1 and n_art == 1:
                # N seq : 1 art -> the one artifact hangs on every seq.
                assignments = [(key, [ids[0]]) for key in keys]
                cases.append(RULE_B)
            elif n_seq == 1 and n_art > 1:
                # 1 seq : N art -> all artifacts hang on that seq.
                assignments = [(keys[0], _unique(ids))]
                cases.append(SPLIT_SAME_SEQ)
            elif n_seq == n_art:
                # N seq : N art -> positional zip (never a Cartesian product).
                assignments = [(key, [aid]) for key, aid in zip(keys, ids)]
                # N:N pairs are rule A unless the seq itself is a range.
                cases.append(RANGE_SPLIT if _is_range(item) else RULE_A)
            else:
                # Counts disagree: report, do not guess any pairing.
                conflicts.append(
                    f"cardinality_mismatch:{','.join(keys)}:{n_seq}seq/{n_art}art"
                )
                continue

            # One clause declared N seq -> 1 art (rule B) deliberately shares
            # that artifact; only a claim from outside the clause can clash.
            shared = n_seq > 1 and n_art == 1
            for key, key_ids in assignments:
                if key in mapping:
                    conflicts.append(f"seq_claimed_by_multiple_clauses:{key}")
                for aid in key_ids:
                    if aid in owner and owner[aid] != key:
                        if not (shared and owner[aid] in keys):
                            conflicts.append(
                                f"artifact_claimed_by_multiple_seqs:{aid}:"
                                f"{owner[aid]}|{key}"
                            )
                    owner[aid] = key
                mapping.setdefault(key, [])
                for aid in key_ids:
                    # The same artifact on several seqs stays on every seq as
                    # conflict evidence; within one seq it appears once.
                    if aid not in mapping[key]:
                        mapping[key].append(aid)

    elif items:
        # Note declares seqs but no artifact ids: weak caption/title fallback.
        seq_keys = [key for item in items for key in _seq_keys(item)]
        caption_ids = _unique(list(caption_artifacts or []))
        if not caption_ids:
            return TextMapping(
                seq_to_artifacts={k: [] for k in seq_keys},
                caption_artifacts=[],
                case_type=SEQ_MISSING,
                conflicts=conflicts,
            )
        n_seq, n_art = len(seq_keys), len(caption_ids)
        if n_seq > 1 and n_art == 1:
            mapping = {key: list(caption_ids) for key in seq_keys}
            cases.append(RULE_B)
        elif n_seq == 1 and n_art > 1:
            mapping = {seq_keys[0]: list(caption_ids)}
            cases.append(SPLIT_SAME_SEQ)
        elif n_seq == n_art:
            mapping = {key: [aid] for key, aid in zip(seq_keys, caption_ids)}
            ranged = any(_is_range(item) for item in items)
            cases.append(RANGE_SPLIT if ranged else RULE_A)
        else:
            # Counts disagree and neither side is a single unit: do not guess.
            conflicts.append(f"caption_cardinality_mismatch:{n_seq}seq/{n_art}art")
    else:
        # No usable note: caption/title only, no seq to bind to.
        caption_only = _unique(list(caption_artifacts or []))
        if not caption_only:
            return TextMapping(
                seq_to_artifacts={},
                caption_artifacts=[],
                case_type=SEQ_MISSING,
                conflicts=conflicts,
            )
        return TextMapping(
            seq_to_artifacts={},
            caption_artifacts=caption_only,
            case_type=SEQ_MISSING,
            conflicts=conflicts,
        )

    # Body artifacts with no seq in the note are recorded, never cartesian-paired.
    mapped = {a for ids in mapping.values() for a in ids}
    for artifact in text_artifacts or []:
        if artifact.artifact_id not in mapped:
            conflicts.append(f"body_artifact_unmapped:{artifact.artifact_id}")

    case_type = _pick_case(cases)
    return TextMapping(
        seq_to_artifacts=mapping,
        # Caption artifacts never enter the mapping while the note has ids.
        caption_artifacts=[],
        case_type=case_type,
        conflicts=conflicts,
    )


def _pick_case(cases: list[str]) -> str:
    if not cases:
        return SEQ_MISSING
    # All clauses mapping one-to-one is rule A; only a genuine N-seq group or
    # same-seq split outranks it.  A range zip is the most specific case.
    if all(case == RULE_A for case in cases):
        return RULE_A
    for preferred in (RANGE_SPLIT, SPLIT_SAME_SEQ, RULE_B, RULE_A):
        if preferred in cases:
            return preferred
    return SEQ_MISSING

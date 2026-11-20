"""Audit one published run directory (pairs.jsonl + pairs/*.png).

Checks that do not need a model:
  * PNG exists, is readable, and carries real ink (junk tiny glyph output);
  * every L1 figure maps each seq/view at most once (no shared drawing);
  * image names are unique and embed the artifact id;
  * status/quality-flag counts.

Usage:
    python audit_run.py <run_dir> [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


def load_rows(run_dir: Path) -> list[dict]:
    path = run_dir / "pairs.jsonl"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def image_stats(path: Path) -> dict:
    raw = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return {"readable": False}
    height, width = image.shape[:2]
    ink = int((image < 160).sum())
    return {
        "readable": True,
        "width": width,
        "height": height,
        "ink": ink,
        "ink_ratio": ink / float(max(1, width * height)),
    }


def audit(run_dir: Path) -> dict:
    rows = load_rows(run_dir)
    status = Counter(row.get("status") for row in rows)
    flags = Counter(
        flag for row in rows for flag in (row.get("quality_flags") or [])
    )
    lines = Counter(
        ((row.get("provenance") or {}).get("mapping") or {}).get("line")
        for row in rows
    )
    problems: list[str] = []
    names: Counter = Counter()
    per_figure_views: dict[str, dict[int, str]] = {}
    per_figure_seqs: dict[str, dict[str, str]] = {}
    images: list[dict] = []

    for row in rows:
        artifact_id = row.get("artifact_id") or ""
        name = Path(str(row.get("image_path") or "")).name
        names[name] += 1
        if artifact_id and artifact_id.replace(":", "-") not in name:
            problems.append(f"name_missing_id: {name} <- {artifact_id}")
        mapping = ((row.get("provenance") or {}).get("mapping") or {})
        case = (row.get("provenance") or {}).get("case")
        shared_ok = bool(row.get("quality_flags") and
                         "shared_image" in row["quality_flags"]) or case == "split_same_seq"
        if mapping.get("line") == "multi_line":
            figure = row.get("figure_id", "")
            for view_id in mapping.get("view_ids") or []:
                seen = per_figure_views.setdefault(figure, {})
                if view_id in seen and seen[view_id] != artifact_id:
                    if not (shared_ok or seen.get((view_id, "shared"))):
                        problems.append(
                            f"view_reused: {figure} view {view_id} "
                            f"{seen[view_id]} + {artifact_id}"
                        )
                seen[view_id] = artifact_id
                seen[(view_id, "shared")] = shared_ok
            for seq_id in mapping.get("seq_ids") or []:
                seen = per_figure_seqs.setdefault(figure, {})
                if seq_id in seen and seen[seq_id] != artifact_id:
                    if not (shared_ok or seen.get((seq_id, "shared"))):
                        problems.append(
                            f"seq_reused: {figure} seq {seq_id} "
                            f"{seen[seq_id]} + {artifact_id}"
                        )
                seen[seq_id] = artifact_id
                seen[(seq_id, "shared")] = shared_ok

        rel = str(row.get("image_path") or "")
        if not rel:
            problems.append(f"missing_image_path: {artifact_id}")
            continue
        stats = image_stats(run_dir / rel)
        stats.update({"name": name, "artifact_id": artifact_id,
                      "status": row.get("status"), "flags": row.get("quality_flags")})
        images.append(stats)
        if not stats.get("readable"):
            problems.append(f"unreadable_image: {rel}")
        elif stats["ink"] < 800 or min(stats["width"], stats["height"]) < 80:
            problems.append(
                f"suspect_junk_image: {rel} {stats['width']}x{stats['height']} "
                f"ink={stats['ink']}"
            )

    for name, count in names.items():
        if count > 1:
            problems.append(f"duplicate_name: {name} x{count}")

    return {
        "run_dir": str(run_dir),
        "pairs": len(rows),
        "status": dict(status),
        "quality_flags": dict(flags),
        "lines": dict(lines),
        "images": images,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit(Path(args.run_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"run: {report['run_dir']}")
        print(f"pairs: {report['pairs']}  status: {report['status']}")
        print(f"flags: {report['quality_flags']}")
        print(f"lines: {report['lines']}")
        print(f"problems: {len(report['problems'])}")
        for problem in report["problems"][:50]:
            print(" -", problem)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
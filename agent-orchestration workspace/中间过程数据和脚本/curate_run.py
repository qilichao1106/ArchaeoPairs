"""Turn audit findings into review records and remove rejected PNGs.

A run must not publish a known-bad image.  This script reuses
``audit_run.audit`` findings and, by default, only prints what would change:

    python curate_run.py <run_dir>          # dry run
    python curate_run.py <run_dir> --apply  # rewrite pairs.jsonl + delete PNGs

Rejected pairs get ``status=review``, an empty ``image_path`` and the extra
``qc_reject`` quality flag.  A PNG is deleted only when no remaining published
pair references it.  The ledger is evidence and is left untouched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from audit_run import audit


def _rejected_artifacts(problems: list[str]) -> set[str]:
    rejected: set[str] = set()
    for problem in problems:
        if problem.startswith("view_reused:") or problem.startswith("seq_reused:"):
            # "... view 15 A + B" / "... seq 3 A + B"
            tail = problem.split(" ", 4)[-1]
            parts = [part.strip() for part in tail.split("+")]
            rejected.update(part for part in parts if part)
        elif problem.startswith("suspect_junk_image:"):
            # mapped by image path below
            continue
    return rejected


def curate(run_dir: Path, *, apply: bool) -> dict:
    report = audit(run_dir)
    pairs_path = run_dir / "pairs.jsonl"
    rows = [json.loads(line)
            for line in pairs_path.read_text(encoding="utf-8").splitlines()]
    by_image = {Path(str(row.get("image_path") or "")).name: row for row in rows}
    rejected = _rejected_artifacts(report["problems"])
    junk_images: set[str] = set()
    for problem in report["problems"]:
        if problem.startswith("suspect_junk_image:"):
            junk_images.add(Path(problem.split(": ", 1)[1].split()[0]).name)
    for name in junk_images:
        row = by_image.get(name)
        if row is not None:
            rejected.add(row.get("artifact_id", ""))

    changed = 0
    for row in rows:
        if row.get("artifact_id") in rejected and row.get("status") != "review":
            row["status"] = "review"
            row["image_path"] = ""
            flags = list(row.get("quality_flags") or [])
            if "qc_reject" not in flags:
                flags.append("qc_reject")
            row["quality_flags"] = flags
            changed += 1
        elif row.get("artifact_id") in rejected:
            row["image_path"] = ""
            flags = list(row.get("quality_flags") or [])
            if "qc_reject" not in flags:
                flags.append("qc_reject")
            row["quality_flags"] = flags

    published = [Path(str(row.get("image_path"))) for row in rows
                 if row.get("status") == "output" and row.get("image_path")]
    deleted: list[str] = []
    if apply:
        pairs_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                      for row in rows) + "\n",
            encoding="utf-8")
        referenced = {str(path) for path in published}
        for name in junk_images:
            rel = Path("pairs") / name
            if str(rel) in referenced:
                continue
            target = run_dir / rel
            if target.is_file():
                target.unlink()
                deleted.append(str(rel))

    return {
        "run_dir": str(run_dir),
        "audit_problems": report["problems"],
        "rejected_artifacts": sorted(rejected),
        "changed_pairs": changed,
        "deleted_images": deleted,
        "apply": apply,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = curate(Path(args.run_dir), apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
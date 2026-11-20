"""Summarise every book run under a batch directory.

Reads each `<book>/pairs.jsonl` and prints one row per book plus totals.  The
ledger is not needed because the CLI log already carries figure statuses; this
script only reports what is in the published pairs.

Usage:
    python summarize_batch.py [runs/batch] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "runs" / "batch"


def book_summary(path: Path) -> dict:
    pairs_path = path / "pairs.jsonl"
    rows = []
    if pairs_path.is_file():
        rows = [json.loads(line)
                for line in pairs_path.read_text(encoding="utf-8").splitlines()]
    status = Counter(row.get("status") for row in rows)
    flags = Counter(flag for row in rows for flag in (row.get("quality_flags") or []))
    lines = Counter(((row.get("provenance") or {}).get("mapping") or {}).get("line")
                    for row in rows)
    return {
        "book": path.name,
        "pairs": len(rows),
        "output": status.get("output", 0),
        "review": status.get("review", 0),
        "flags": dict(flags),
        "lines": dict(lines),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", nargs="?", default=str(DEFAULT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    base = Path(args.batch_dir)
    if not base.is_dir():
        raise SystemExit(f"missing {base}")
    rows = [book_summary(path) for path in sorted(base.iterdir())
            if path.is_dir() and path.name != "logs"]
    total = {
        "books": len(rows),
        "pairs": sum(row["pairs"] for row in rows),
        "output": sum(row["output"] for row in rows),
        "review": sum(row["review"] for row in rows),
        "flags": dict(sum((Counter(row["flags"]) for row in rows), Counter())),
    }
    if args.json:
        print(json.dumps({"total": total, "books": rows},
                         ensure_ascii=False, indent=1))
    else:
        print(f"{'book':40s} {'pairs':>6s} {'output':>6s} {'review':>6s}  flags")
        for row in rows:
            print(f"{row['book'][:40]:40s} {row['pairs']:6d} {row['output']:6d} "
                  f"{row['review']:6d}  {row['flags']}")
        print(f"{'TOTAL':40s} {total['pairs']:6d} {total['output']:6d} "
              f"{total['review']:6d}  {total['flags']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
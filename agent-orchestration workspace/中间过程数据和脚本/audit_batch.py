"""Audit every finished book in a batch directory.

Usage:
    python audit_batch.py [runs/batch] [--json]

Only books with a pairs.jsonl are audited; unfinished books are listed as such.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audit_run import audit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "runs" / "batch"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", nargs="?", default=str(DEFAULT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    base = Path(args.batch_dir)
    rows = []
    problems = 0
    for path in sorted(base.iterdir()):
        if not path.is_dir() or path.name == "logs":
            continue
        if not (path / "pairs.jsonl").is_file():
            rows.append({"book": path.name, "state": "unfinished"})
            continue
        report = audit(path)
        problems += len(report["problems"])
        rows.append({
            "book": path.name,
            "state": "ok" if not report["problems"] else "problems",
            "pairs": report["pairs"],
            "status": report["status"],
            "flags": report["quality_flags"],
            "problems": report["problems"],
        })
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for row in rows:
            if row["state"] == "unfinished":
                print(f"{row['book'][:40]:40s} unfinished")
                continue
            print(f"{row['book'][:40]:40s} {row['state']:9s} "
                  f"pairs={row['pairs']} status={row['status']} "
                  f"flags={row['flags']}")
            for problem in row["problems"][:10]:
                print("   -", problem)
        print(f"TOTAL problems: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
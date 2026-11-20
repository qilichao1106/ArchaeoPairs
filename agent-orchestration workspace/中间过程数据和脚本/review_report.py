"""Summarise review reasons from one run's ledger.jsonl.

The CLI log already reports figure counts; this report explains *why* a pair
needs review and which figures produced no pair at all.

Usage:
    python review_report.py <run_dir> [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    ledger_path = run_dir / "ledger.jsonl"
    if not ledger_path.is_file():
        raise SystemExit(f"missing {ledger_path}")

    figures: dict[str, list[dict]] = defaultdict(list)
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        figures[row.get("figure_id", "")].append(row)

    review_pairs: list[dict] = []
    no_pairs: list[dict] = []
    flags = Counter()
    alarms = Counter()
    for figure_id, rows in sorted(figures.items()):
        pair_rows = [row for row in rows if row.get("artifact_id")]
        if not pair_rows:
            kinds = [row.get("kind") for row in rows]
            no_pairs.append({"figure_id": figure_id, "kinds": kinds})
            continue
        for row in pair_rows:
            for flag in row.get("quality_flags") or []:
                flags[flag] += 1
            for alarm in row.get("alarms") or []:
                alarms[alarm] += 1
            if row.get("status") == "review":
                review_pairs.append({
                    "figure_id": figure_id,
                    "artifact_id": row.get("artifact_id"),
                    "flags": row.get("quality_flags"),
                    "alarms": row.get("alarms"),
                    "conflicts": row.get("conflicts"),
                    "unbound": row.get("unbound"),
                })

    report = {
        "run_dir": str(run_dir),
        "figures": len(figures),
        "figures_without_pairs": len(no_pairs),
        "review_pairs": len(review_pairs),
        "quality_flags": dict(flags),
        "alarms": dict(alarms),
        "review": review_pairs,
        "without_pairs": no_pairs,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"run: {run_dir}")
        print(f"figures: {report['figures']}  no-pair: {report['figures_without_pairs']}"
              f"  review pairs: {report['review_pairs']}")
        print(f"flags: {report['quality_flags']}")
        print(f"alarms: {report['alarms']}")
        for item in review_pairs[:30]:
            print(" -", item["figure_id"], item["artifact_id"], item["flags"],
                  item["alarms"], item["conflicts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
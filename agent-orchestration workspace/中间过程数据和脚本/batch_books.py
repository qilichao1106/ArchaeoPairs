"""Run every book under books/ through the product CLI, with bounded parallelism.

Each book is one subprocess (the CLI writes pairs.jsonl/ledger.jsonl/PNGs into
runs/batch/<book>).  Logs go to runs/batch/logs/<book>.log.  Books that already
have a complete pairs.jsonl are skipped unless --force is given, so a crashed
batch can be resumed.

Usage:
    python batch_books.py --workers 4 [--books 万州瓦子坪 ...] [--force]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOKS = ROOT / "books"
OUT = ROOT / "runs" / "batch"
SRC = ROOT / "src"


def safe_name(name: str) -> str:
    keep = []
    for char in name:
        keep.append(char if char not in '<>:"/\\|?*' else "_")
    return "".join(keep)


def book_dirs() -> list[Path]:
    return sorted(
        path for path in BOOKS.iterdir()
        if path.is_dir() and (path / "data.xml").is_file()
    )


def run_book(path: Path, force: bool) -> dict:
    name = path.name
    out = OUT / safe_name(name)
    log_dir = OUT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{safe_name(name)}.log"
    if not force and (out / "pairs.jsonl").is_file():
        return {"book": name, "state": "skipped", "out": str(out)}

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            [sys.executable, "-m", "archaeopairs.cli", "run-book",
             "--book", name, "--out", str(out)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
    elapsed = round(time.time() - started, 1)
    state = "ok" if process.returncode == 0 else f"failed:{process.returncode}"
    return {"book": name, "state": state, "seconds": elapsed,
            "out": str(out), "log": str(log_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--books", nargs="*", default=None)
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    selected = book_dirs()
    if args.exclude:
        excluded = set(args.exclude)
        selected = [path for path in selected if path.name not in excluded]
    if args.books:
        wanted = set(args.books)
        selected = [path for path in selected if path.name in wanted]
        missing = wanted - {path.name for path in selected}
        if missing:
            raise SystemExit(f"unknown books: {sorted(missing)}")
    if not os.environ.get("DASHSCOPE_API_KEY"):
        raise SystemExit("DASHSCOPE_API_KEY is not set")

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_book, path, args.force): path
                   for path in selected}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)

    (OUT / "batch_manifest.json").write_text(
        json.dumps(sorted(results, key=lambda item: item["book"]),
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    failed = [item for item in results if not item["state"].startswith("ok")
              and item["state"] != "skipped"]
    print(json.dumps({"books": len(results), "failed": failed,
                      "changed": len([r for r in results if r["state"] == "ok"])},
                     ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
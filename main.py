# -*- coding: utf-8 -*-
"""CLI 入口：对一本考古报告运行图文 Pair 构造流水线。

用法：
  python main.py run --xml examples/奉节白帝城（白帝村、白帝山、紫阳城遗址）/data.xml \
      --media examples/奉节白帝城（白帝村、白帝山、紫阳城遗址）/media \
      --book baidicheng --max-figures 50
  python main.py resume --book baidicheng --thread <trace_id> --kind mapping
说明：默认使用 MockGateway（无 GPU 联调），VLM/SAM/OCR 相关节点将 fail-closed
进入复核队列——这正是 P1 阶段"最小链+人工补缺"的预期行为（方案 §1.4/附录D）。
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from archaeopairs.agents import AGENTS, BookIndexer, build_artifact_records
from archaeopairs.gateway import RecordingGateway, MockGateway
from archaeopairs.orchestration.graph import Checkpointer, GraphRunner
from archaeopairs.state import PairState
from archaeopairs.storage import db as store


@dataclass
class CliContext:
    """AgentContext 实现：注入网关/配置/产物目录。"""
    gateway: object
    config: dict = field(default_factory=dict)
    book_dir: str = ""


def cmd_run(args) -> int:
    indexer = BookIndexer(args.xml, args.media, args.book)
    index = indexer.parse()
    records = build_artifact_records(index.body_paras)
    print(f"[A0] 报告解析完成: figures={len(index.figures)} "
          f"body_paras={len(index.body_paras)} artifact_records={len(records)}")

    book_dir = store.init_book_dirs(args.data_root, args.book)
    conn = store.init_db(str(book_dir / "archaeopairs.db"))
    conn.execute("INSERT OR IGNORE INTO books VALUES(?,?,?,?,datetime('now'))",
                 (args.book, Path(args.xml).stem, "", ""))
    conn.commit()

    gateway = RecordingGateway(
        MockGateway(ocr_available=args.mock_ocr, sam_available=args.mock_sam),
        record_path=str(book_dir / "logs" / "model_calls.jsonl"))
    runner = GraphRunner(AGENTS, Checkpointer(str(book_dir / "checkpoints.db")))

    figures = index.figures[: args.max_figures] if args.max_figures else index.figures
    stats = {"finished": 0, "blocked_review": 0, "failed": 0, "archived": 0}
    t0 = time.time()
    for rec in figures:
        state = PairState(book_id=args.book, figure_id=rec.figure_id,
                          trace_id=f"{args.book}:{rec.figure_id}:r1:p1")
        ctx = CliContext(gateway=gateway, book_dir=str(book_dir),
                         config={"__figure__": rec,
                                 "__artifact_records__": records})
        result = runner.run(state, ctx)
        stats[result.status] += 1
        store.upsert_figure(conn, state,
                            {"finished": "final", "blocked_review": "blocked_review",
                             "failed": "rejected", "archived": "final"}[result.status])
        if result.review:
            store.open_review_task(conn, state, result.review["kind"])
        conn.commit()
        if args.verbose:
            print(f"  {rec.figure_id} [{result.status}] type={state.figure_type} "
                  f"pairs={result.pairs} conf={state.confidence:.2f} {result.error}")

    dt = time.time() - t0
    print(f"[done] {stats} 耗时 {dt:.1f}s；复核队列见 {book_dir}/archaeopairs.db:review_tasks")
    print(f"[metrics] 模型调用 {len(gateway.metrics)} 次（Mock 模式）")
    return 0


def cmd_resume(args) -> int:
    book_dir = Path(args.data_root) / args.book
    runner = GraphRunner(AGENTS, Checkpointer(str(book_dir / "checkpoints.db")))
    gateway = RecordingGateway(MockGateway(ocr_available=args.mock_ocr,
                                           sam_available=args.mock_sam))
    ctx = CliContext(gateway=gateway, book_dir=str(book_dir), config={})
    # TODO: patch 数据应由 Label Studio webhook 携带（复核界面回传修正后的映射/掩膜）
    result = runner.resume(args.thread, ctx,
                           {"kind": args.kind, "patch": {}})
    print(f"[resume] {result.figure_id} [{result.status}] pairs={result.pairs} {result.error}")
    return 0 if result.status in ("finished", "archived") else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="archaeopairs")
    ap.add_argument("--data-root", default="data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--xml", required=True)
    pr.add_argument("--media", required=True)
    pr.add_argument("--book", required=True)
    pr.add_argument("--max-figures", type=int, default=0)
    pr.add_argument("--mock-ocr", action="store_true", help="Mock OCR 可用（联调用）")
    pr.add_argument("--mock-sam", action="store_true", help="Mock SAM 可用（联调用）")
    pr.add_argument("-v", "--verbose", action="store_true")
    ps = sub.add_parser("resume")
    ps.add_argument("--book", required=True)
    ps.add_argument("--thread", required=True)
    ps.add_argument("--kind", default="mapping",
                    choices=["mapping", "mask", "text", "qc"])
    ps.add_argument("--mock-ocr", action="store_true")
    ps.add_argument("--mock-sam", action="store_true")
    args = ap.parse_args()
    return {"run": cmd_run, "resume": cmd_resume}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

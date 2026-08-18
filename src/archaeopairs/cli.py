"""CLI：跑批入口（P0 用 mock 能力接口）。

支持两种输入方式：
  1) 指定单本书：python -m archaeopairs.cli run-book --book 郑州商城 [--books-dir books]
  2) 指定目录批量：python -m archaeopairs.cli run-books [--books-dir books]
数据目录默认 books/（每本书一个子目录，内含 data.xml）。
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from . import naming
from .agents import Services
from .agents import s3 as s3_agent
from .capability import MockOCR, MockSAM, MockVLM
from .capability.compose import MockCompositor
from .config import load_flags, load_thresholds
from .gateway import Gateway
from .integrations import MockReviewBridge
from .orchestration import build_graph
from .parsers import s1_xml, s3_note
from .storage import DiagnosticReportRow, FigureStateRow, LocalObjectStore, PairRecordRow, make_session_factory

_VERSIONS = ("r1", "p1", "j1")


def _find_data_xml(books_dir: Path, book: str) -> Path:
    for p in (books_dir / book).rglob("data.xml"):
        return p
    raise FileNotFoundError(f"books/{book}/data.xml not found")


def _book_has_artifact(body_paras: list[dict], figures) -> bool:
    """无器物号报告前置检测（§2.5）：正文、图注或图题出现器物号信号。"""
    for p in body_paras:
        if s3_note.ARTIFACT_RE.search(p.get("text", "")) or s3_note.COMPONENT_RE.search(p.get("text", "")):
            return True
    for fig in figures:
        if fig.figure_note and (s3_note.ARTIFACT_RE.search(fig.figure_note)
                                or s3_note.COMPONENT_RE.search(fig.figure_note)):
            return True
        if s3_note.extract_caption_artifacts(fig.caption):  # 图题兜底信号（§2.2.5）
            return True
    return False


def run_book(book: str, books_dir: str = "books", db: str = "runs/checkpoints.sqlite3",
             limit: int | None = None, persist: bool = False) -> dict:
    root = Path(books_dir)
    xml = _find_data_xml(root, book)
    figures, ground, violations = s1_xml.parse_report(xml, book)
    body_paras = s1_xml.parse_body(xml)
    if limit:
        figures = figures[:limit]

    # 报告级无器物号检测（§2.5）：整书排除而非逐图处理
    if not _book_has_artifact(body_paras, figures):
        return {"figures": len(figures), "violations": violations, "pairs": 0,
                "statuses": {}, "records": [],
                "excluded_reason": "no_artifact_id"}

    thresholds = load_thresholds()
    flags = load_flags()
    store = LocalObjectStore("runs/objects")
    svc = Services(vlm=MockVLM(ground), sam=MockSAM(ground), ocr=MockOCR(ground),
                   gateway=Gateway(timeouts=thresholds.timeouts, rate_limits=thresholds.rate_limits),
                   thresholds=thresholds, flags=flags,
                   object_store=store, compositor=MockCompositor(store),
                   review_bridge=MockReviewBridge(), ground=ground)

    session_factory = make_session_factory(f"sqlite:///{db}.meta.sqlite3") if persist else None
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    pair_rows: list[dict] = []
    statuses: dict[str, str] = {}
    with SqliteSaver.from_conn_string(db) as ckpt:
        app = build_graph(svc, checkpointer=ckpt)
        for fig in figures:
            rule_v, prompt_v, judge_v = _VERSIONS
            thread_id = f"{fig.book_id}:{fig.figure_id}:{rule_v}:{prompt_v}:{judge_v}"
            # 正文预筛选：只把与该图相关的段落注入 State（修复 checkpoint 膨胀）
            note_items = s3_note.parse_note(fig.figure_note or "")
            note_arts = {a for it in note_items for a in it.artifact_ids}
            # 图题器物号兜底（§2.2.5）：与 S3 同口径参与正文筛选
            caption_arts = [] if note_arts else s3_note.extract_caption_artifacts(fig.caption)
            fig_number = naming.extract_fig_number(fig.caption)
            paras = s3_agent.select_paras(body_paras, note_arts | set(caption_arts), fig_number)
            init = {
                "book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
                "caption": fig.caption, "figure_note": fig.figure_note,
                "book_has_artifact": True,
                "image_base": str(xml.parent),
                "body_paras": paras,
                "iteration": 0, "defect_history": [], "assembled": False,
                "trace_id": str(uuid.uuid4()), "flags": flags.model_dump(),
                "status": "INIT",
            }
            result = app.invoke(init, config={"configurable": {"thread_id": thread_id}})
            statuses[fig.figure_id] = result.get("status", "?")
            pair_rows.extend(result.get("pair_records", []))
            if session_factory is not None:
                _persist(session_factory, fig, result)
    pairs = pair_rows  # V0.4 范围：按单图独立输出，不做跨图聚合
    return {"figures": len(figures), "violations": violations,
            "pairs": len(pairs), "statuses": statuses, "records": pairs}


def run_books(books_dir: str = "books", db: str = "runs/checkpoints.sqlite3",
              limit: int | None = None, persist: bool = False) -> dict:
    """目录批量：跑 books_dir 下所有含 data.xml 的书（子目录即书名）。"""
    root = Path(books_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"books 目录不存在: {books_dir}")
    results: dict[str, dict] = {}
    total_pairs = 0
    total_figures = 0
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        if not any(sub.rglob("data.xml")):
            continue  # 跳过非书目录（无 data.xml）
        book = sub.name
        out = run_book(book, books_dir=str(root), db=db, limit=limit, persist=persist)
        results[book] = {k: v for k, v in out.items() if k != "records"}
        total_pairs += out.get("pairs", 0)
        total_figures += out.get("figures", 0)
    return {"books_dir": str(root), "books": len(results),
            "total_figures": total_figures, "total_pairs": total_pairs,
            "results": results}


def _persist(session_factory, fig, result: dict) -> None:
    with session_factory() as s:
        fs = FigureStateRow(book_id=fig.book_id, figure_id=fig.figure_id, fileref=fig.fileref,
                            caption=fig.caption, figure_note=fig.figure_note,
                            image_type=result.get("image_type"), status=result.get("status"),
                            iteration=result.get("iteration", 0), case_type=result.get("case_type"),
                            trace_id=result.get("trace_id"))
        s.add(fs)
        s.flush()
        if result.get("diagnostic"):
            s.add(DiagnosticReportRow(figure_state_id=fs.id,
                                      iteration=result.get("iteration", 0),
                                      report=result["diagnostic"]))
        for pr in result.get("pair_records", []):
            s.add(PairRecordRow(book_id=pr["book_id"], artifact_id=pr["artifact_id"],
                                image_path=pr["image_path"],
                                candidate_images=pr.get("candidate_images", []),
                                image_merge_mode=pr.get("image_merge_mode", "line_only"),
                                description_text=pr.get("description_text"),
                                provenance=pr.get("provenance"),
                                quality_flags=pr.get("quality_flags")))
        s.commit()


def main() -> None:
    ap = argparse.ArgumentParser(prog="archaeopairs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rb = sub.add_parser("run-book", help="处理单本书")
    rb.add_argument("--book", required=True, help="书名（books/<书名>/data.xml）")
    rb.add_argument("--books-dir", default="books", help="书籍根目录（默认 books）")
    rb.add_argument("--db", default="runs/checkpoints.sqlite3")
    rb.add_argument("--limit", type=int, default=None, help="仅处理前 N 图（调试）")
    rb.add_argument("--persist", action="store_true", help="落库 FigureState/PairRecord")
    rbs = sub.add_parser("run-books", help="批量处理目录下所有书")
    rbs.add_argument("--books-dir", default="books", help="书籍根目录（默认 books）")
    rbs.add_argument("--db", default="runs/checkpoints.sqlite3")
    rbs.add_argument("--limit", type=int, default=None, help="每本仅处理前 N 图（调试）")
    rbs.add_argument("--persist", action="store_true", help="落库 FigureState/PairRecord")
    args = ap.parse_args()
    if args.cmd == "run-book":
        out = run_book(args.book, args.books_dir, args.db, args.limit, args.persist)
        print(json.dumps({k: v for k, v in out.items() if k != "records"},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "run-books":
        out = run_books(args.books_dir, args.db, args.limit, args.persist)
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

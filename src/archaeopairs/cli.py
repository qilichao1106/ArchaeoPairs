"""CLI：跑批入口（P0 用 mock 能力接口）。

用法：python -m archaeopairs.cli run-book --book 郑州商城 --examples examples/
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from .agents import Services
from .capability import MockOCR, MockSAM, MockVLM
from .capability.compose import MockCompositor
from .config import load_flags, load_thresholds
from .gateway import Gateway
from .integrations import MockReviewBridge
from .orchestration import build_graph
from .parsers import s1_xml
from .storage import DiagnosticReportRow, FigureStateRow, LocalObjectStore, PairRecordRow, make_session_factory

_VERSIONS = ("r1", "p1", "j1")


def _find_data_xml(examples_dir: Path, book: str) -> Path:
    for p in (examples_dir / book).rglob("data.xml"):
        return p
    raise FileNotFoundError(f"examples/{book}/data.xml not found")


def run_book(book: str, examples_dir: str = "examples", db: str = "runs/checkpoints.sqlite3",
             limit: int | None = None, persist: bool = False) -> dict:
    examples = Path(examples_dir)
    xml = _find_data_xml(examples, book)
    figures, ground, violations = s1_xml.parse_report(xml, book)
    body_paras = s1_xml.parse_body(xml)
    if limit:
        figures = figures[:limit]

    thresholds = load_thresholds()
    flags = load_flags()
    store = LocalObjectStore("runs/objects")
    svc = Services(vlm=MockVLM(ground), sam=MockSAM(ground), ocr=MockOCR(ground),
                   gateway=Gateway(per_figure_cap_cny=thresholds.per_figure_cap_cny),
                   thresholds=thresholds, flags=flags,
                   object_store=store, compositor=MockCompositor(store),
                   review_bridge=MockReviewBridge(), ground=ground)

    session_factory = make_session_factory(f"sqlite:///{db}.meta.sqlite3") if persist else None
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    pairs: list[dict] = []
    statuses: dict[str, str] = {}
    with SqliteSaver.from_conn_string(db) as ckpt:
        app = build_graph(svc, checkpointer=ckpt)
        for fig in figures:
            rule_v, prompt_v, judge_v = _VERSIONS
            thread_id = f"{fig.book_id}:{fig.figure_id}:{rule_v}:{prompt_v}:{judge_v}"
            init = {
                "book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
                "caption": fig.caption, "figure_note": fig.figure_note,
                "body_paras": body_paras,
                "iteration": 0, "defect_history": [], "assembled": False,
                "trace_id": str(uuid.uuid4()), "flags": flags.model_dump(),
                "status": "INIT",
            }
            result = app.invoke(init, config={"configurable": {"thread_id": thread_id}})
            statuses[fig.figure_id] = result.get("status", "?")
            pairs.extend(result.get("pair_records", []))
            svc.gateway.reset_figure(fig.figure_id)
            if session_factory is not None:
                _persist(session_factory, fig, result)
    return {"figures": len(figures), "violations": violations,
            "pairs": len(pairs), "statuses": statuses, "records": pairs}


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
                                description_text=pr.get("description_text"),
                                provenance=pr.get("provenance"),
                                quality_flags=pr.get("quality_flags")))
        s.commit()


def main() -> None:
    ap = argparse.ArgumentParser(prog="archaeopairs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rb = sub.add_parser("run-book")
    rb.add_argument("--book", required=True)
    rb.add_argument("--examples", default="examples")
    rb.add_argument("--db", default="runs/checkpoints.sqlite3")
    args = ap.parse_args()
    if args.cmd == "run-book":
        out = run_book(args.book, args.examples, args.db)
        print(json.dumps({k: v for k, v in out.items() if k != "records"},
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

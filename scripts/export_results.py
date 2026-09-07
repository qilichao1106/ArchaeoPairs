"""Export ArchaeoPairs checkpoint results to JSON, CSV and an offline HTML board."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from archaeopairs.parsers import s1_xml, s3_text

STATUS_CLASSES = {
    "OUTPUT": "ok",
    "PENDING_REVIEW": "review",
    "EXCLUDED": "excluded",
    "FAILED": "failed",
    "DEGRADED": "review",
}


def _image_sort_key(figure_id: str) -> tuple[int, int, str]:
    """Order imageNNN numerically while keeping unknown ids at the end."""
    match = re.search(r"image(\d+)$", figure_id)
    if match:
        return (0, int(match.group(1)), figure_id)
    return (1, 0, figure_id)


def _thread_ids(db: Path) -> list[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
    return [str(row[0]) for row in rows]


def _json_safe(value: Any) -> Any:
    """Convert tuples and other checkpoint values into JSON-friendly structures."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _collect_states(db: Path) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    with SqliteSaver.from_conn_string(str(db)) as saver:
        for thread_id in _thread_ids(db):
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint_tuple = saver.get_tuple(config)
            if checkpoint_tuple is None:
                continue
            values = checkpoint_tuple.checkpoint.get("channel_values") or {}
            if values.get("figure_id"):
                states.append(_json_safe(values))
    return states


def _load_pair_rows(objects_dir: Path, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        for pair in state.get("pair_records") or []:
            image_path = pair.get("image_path", "")
            image = objects_dir / image_path
            rows.append({
                "figure_id": state.get("figure_id", ""),
                "status": state.get("status", ""),
                "artifact_id": pair.get("artifact_id", ""),
                "image_path": image_path,
                "image_exists": "yes" if image.is_file() else "no",
                "image_merge_mode": pair.get("image_merge_mode", ""),
                "description_text": s3_text.strip_figure_locations(str(pair.get("description_text") or "")),
                "case": (pair.get("provenance") or {}).get("case", ""),
                "views": (pair.get("provenance") or {}).get("views", ""),
                "art_source": (pair.get("provenance") or {}).get("art_source", ""),
            })
    return rows


def _load_s1_violations(books_dir: Path, states: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    book_ids = sorted({str(s.get("book_id", "")) for s in states if s.get("book_id")})
    for book_id in book_ids:
        xml_candidates = list((books_dir / book_id).rglob("data.xml"))
        if not xml_candidates:
            continue
        _, _, book_violations = s1_xml.parse_report(xml_candidates[0], book_id)
        violations.extend(book_violations)
    return violations


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _badge(value: str) -> str:
    cls = STATUS_CLASSES.get(value, "other")
    return f'<span class="badge {cls}">{html.escape(value)}</span>'


def _detail(title: str, value: Any) -> str:
    pretty = html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    return f"<details><summary>{html.escape(title)}</summary><pre>{pretty}</pre></details>"


def _render_html(
    path: Path,
    states: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    objects_dir: Path,
    s1_violations: list[str],
    source_rels: dict[str, str],
) -> None:
    status_counts = Counter(s.get("status", "UNKNOWN") for s in states)
    output_count = status_counts.get("OUTPUT", 0)
    review_count = status_counts.get("PENDING_REVIEW", 0)
    excluded_count = status_counts.get("EXCLUDED", 0)
    s1_html = _detail(f"S1 violations ({len(s1_violations)})", s1_violations)
    states = sorted(states, key=lambda state: _image_sort_key(str(state.get("figure_id", ""))))

    figure_cards = []
    image_count = 0
    for state in states:
        status = str(state.get("status", "UNKNOWN"))
        figure_id = str(state.get("figure_id", "unknown"))
        pairs = state.get("pair_records") or []
        qc = state.get("qc_report") or {}
        defects = qc.get("defect_list") or []
        alarms = state.get("alarms") or []
        source_items = []
        artifact_items = []
        source_rel = source_rels.get(figure_id, "")
        if source_rel:
            image_count += 1
            source_items.append(
                '<figure class="image-item">'
                f'<a href="{html.escape(source_rel)}" target="_blank" rel="noreferrer">'
                f'<img src="{html.escape(source_rel)}" alt="原图 {html.escape(figure_id)}" loading="lazy"></a>'
                '<figcaption>source</figcaption>'
                "</figure>"
            )
        text_by_artifact = {
            str(item.get("artifact_id", "")): str(item.get("text") or "").strip()
            for item in (state.get("text_artifacts") or [])
        }
        for pair in pairs:
            rel = str(pair.get("image_path") or "")
            rel_from_report = Path(os.path.relpath(objects_dir / rel, path.parent))
            src = rel_from_report.as_posix() if rel else ""
            artifact_id = str(pair.get("artifact_id", ""))
            desc = s3_text.strip_figure_locations(
                text_by_artifact.get(artifact_id, "")
                or str(pair.get("description_text") or "")
            )
            if src:
                image_count += 1
                artifact_items.append(
                    '<figure class="artifact-item">'
                    f'<a href="{html.escape(src)}" target="_blank" rel="noreferrer">'
                    f'<img src="{html.escape(src)}" alt="{html.escape(artifact_id)}" loading="lazy"></a>'
                    f'<figcaption class="artifact-id">{html.escape(artifact_id)}</figcaption>'
                    '<p class="artifact-desc">'
                    + (html.escape(desc) if desc else "No exact body-text match")
                    + "</p>"
                    "</figure>"
                )
        notices = []
        if status == "EXCLUDED" and state.get("exclude_reason"):
            notices.append(
                '<div class="notice excluded-note">排除原因: '
                f'{html.escape(str(state.get("exclude_reason")))}</div>'
            )
        if status == "PENDING_REVIEW" and alarms:
            alarm_text = ", ".join(str(a) for a in alarms)
            notices.append(
                '<div class="notice review-note">alarm: '
                f'{html.escape(alarm_text)}</div>'
            )
        details = []
        if qc:
            details.append(_detail("qc_report", qc))
        if state.get("fused"):
            details.append(_detail("fused", state.get("fused")))
        if state.get("vision_units"):
            details.append(_detail("vision_units", state.get("vision_units")))
        if state.get("view_groups"):
            details.append(_detail("view_groups", state.get("view_groups")))

        figure_cards.append(
            '<article class="figure-card" data-status="'
            + html.escape(status)
            + '"><header><h3>'
            + html.escape(figure_id)
            + '</h3><div>'
            + _badge(status)
            + f'<span class="count">{len(pairs)} pairs</span></div></header>'
            + f'<p class="caption">{html.escape(str(state.get("caption") or ""))}</p>'
            + ('<div class="defects">QC defects: '
               + html.escape(json.dumps(defects, ensure_ascii=False)) + "</div>" if defects else "")
            + (f'<div class="images">{"".join(source_items)}</div>' if source_items else "")
            + ("".join(notices) if notices else "")
            + (f'<div class="artifact-grid pair-images">{"".join(artifact_items)}</div>'
               if artifact_items else "")
            + (f'<div class="details">{"".join(details)}</div>' if details else "")
            + "</article>"
        )

    card_html = "".join(figure_cards)
    page = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ArchaeoPairs Results</title>
<style>
:root { color-scheme: light; --line:#d9d9de; --ink:#202124; --muted:#666a73; --bg:#f6f6f7; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 Arial,"Microsoft YaHei",sans-serif; }
header { position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; }
h1 { margin:0 0 12px; font-size:20px; font-weight:650; }
.toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.toolbar input { min-width:220px; padding:8px 10px; border:1px solid var(--line); border-radius:4px; }
.toolbar button, .toolbar select { padding:8px 10px; border:1px solid var(--line); background:#fff; border-radius:4px; }
.kpis { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
.stat { background:#fff; border:1px solid var(--line); border-radius:4px; padding:10px 14px; min-width:98px; }
.stat strong { display:block; font-size:20px; }
.stat span { color:var(--muted); }
main { padding:18px 24px 40px; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
gap:14px; }
.figure-card { display:flex; flex-direction:column; background:#fff; border:1px solid var(--line);
border-radius:6px; padding:14px; }
.figure-card header { display:flex; justify-content:space-between; gap:8px; position:static;
background:transparent; border:0; padding:0; }
.figure-card h3 { margin:0; font-size:16px; overflow-wrap:anywhere; }
.figure-card header > div { display:flex; align-items:center; gap:6px; }
.caption { margin:8px 0 0; color:var(--muted); overflow-wrap:anywhere; }
.badge { padding:2px 6px; border-radius:3px; font-size:12px; white-space:nowrap; }
.badge.ok { background:#dff3e7; color:#17643a; }
.badge.review { background:#fff0d6; color:#8a5200; }
.badge.excluded { background:#ececee; color:#52565e; }
.badge.failed { background:#fde4e4; color:#9d1c1c; }
.badge.other { background:#e8f0fe; color:#1f4c9c; }
.count { color:var(--muted); font-size:12px; }
.defects { margin-top:8px; padding:8px; border-left:3px solid #e0a000; background:#fff8e6; overflow-wrap:anywhere; }
.images { margin-top:10px; display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)); gap:8px; }
.image-item { margin:0; display:flex; flex-direction:column; gap:4px; }
.image-item a { display:block; aspect-ratio:1; border:1px solid var(--line); border-radius:3px;
overflow:hidden; background:#fafafa; }
.image-item img { width:100%; height:100%; object-fit:contain; }
.image-item figcaption { font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.notice { margin-top:8px; padding:8px; border-radius:3px; overflow-wrap:anywhere; }
.excluded-note { border-left:3px solid #8a8f98; background:#f0f0f2; color:#44484f; }
.review-note { border-left:3px solid #e0a000; background:#fff8e6; color:#7a4a00; }
.artifact-grid { margin-top:10px; display:grid; gap:12px; }
.artifact-item { margin:0; min-width:0; }
.artifact-item > a { display:block; aspect-ratio:1; border:1px solid var(--line); border-radius:3px;
overflow:hidden; background:#fafafa; }
.artifact-item img { width:100%; height:100%; object-fit:contain; }
.artifact-id { margin-top:6px; font-size:13px; font-weight:650; overflow-wrap:anywhere; }
.artifact-desc { margin:4px 0 0; padding:8px; border-left:3px solid #c7cad0; background:#fbfbfc;
font-size:13px; white-space:pre-wrap; overflow-wrap:anywhere; max-height:240px; overflow:auto; }
.details { margin-top:10px; }
details { margin-top:6px; border-top:1px solid var(--line); padding-top:6px; }
summary { cursor:pointer; color:#1f4c9c; }
pre { max-height:220px; overflow:auto; margin:6px 0 0; background:#f8f8f9; border:1px solid var(--line); padding:8px; }
.empty { margin-top:20px; color:var(--muted); }
@media (max-width:640px) { header,main { padding-left:12px; padding-right:12px; }
.cards { grid-template-columns:1fr; } .toolbar input { min-width:0; flex:1; } }
</style>
</head>
<body>
<header>
<h1>ArchaeoPairs \u5168\u91cf\u7ed3\u679c\u770b\u677f</h1>
<div class="toolbar">
<input id="search" placeholder="\u641c\u7d22\u56fe\u53f7\u3001\u5668\u7269\u53f7\u6216\u63cf\u8ff0">
<select id="status">
<option value="">\u5168\u90e8\u72b6\u6001</option>
<option value="OUTPUT">OUTPUT</option>
<option value="PENDING_REVIEW">PENDING_REVIEW</option>
<option value="EXCLUDED">EXCLUDED</option>
<option value="DEGRADED">DEGRADED</option>
<option value="FAILED">FAILED</option>
</select>
<button type="button" id="onlyOutput">only pair</button>
</div>
<div class="kpis">
<div class="stat"><strong>__FIGURES__</strong><span>figures</span></div>
<div class="stat"><strong>__PAIRS__</strong><span>pair records</span></div>
<div class="stat"><strong>__IMAGES__</strong><span>images</span></div>
<div class="stat"><strong>__OUTPUT__</strong><span>OUTPUT</span></div>
<div class="stat"><strong>__REVIEW__</strong><span>PENDING_REVIEW</span></div>
<div class="stat"><strong>__EXCLUDED__</strong><span>EXCLUDED</span></div>
<div class="stat"><strong>__S1_VIOLATIONS__</strong><span>S1 violations</span></div>
</div>
</header>
<main>
__S1_HTML__
<div class="cards">__CARD_HTML__</div>
__EMPTY__
</main>
<script>
const cards=[...document.querySelectorAll(".figure-card")];
const search=document.querySelector("#search"),status=document.querySelector("#status");
let onlyOutput=false;
function apply(){const q=search.value.trim().toLowerCase(),s=status.value;
cards.forEach(c=>{const text=c.textContent.toLowerCase(),st=c.dataset.status;
const visible=(!q||text.includes(q))&&(!s||st===s)&&(!onlyOutput||c.querySelector(".pair-images"));
c.style.display=visible?"":"none";});}
search.addEventListener("input",apply);status.addEventListener("change",apply);
document.querySelector("#onlyOutput").addEventListener("click",e=>{onlyOutput=!onlyOutput;
e.target.textContent=onlyOutput?"\u663e\u793a\u5168\u90e8":"only pair";apply();});
apply();
</script>
</body>
</html>"""
    page = page.replace("__FIGURES__", str(len(states)))
    page = page.replace("__PAIRS__", str(len(pair_rows)))
    page = page.replace("__IMAGES__", str(image_count))
    page = page.replace("__OUTPUT__", str(output_count))
    page = page.replace("__REVIEW__", str(review_count))
    page = page.replace("__EXCLUDED__", str(excluded_count))
    page = page.replace("__S1_VIOLATIONS__", str(len(s1_violations)))
    page = page.replace("__S1_HTML__", s1_html)
    page = page.replace("__CARD_HTML__", card_html)
    page = page.replace("__EMPTY__", "" if states else '<p class="empty">No figure states found.</p>')
    path.write_text(page, encoding="utf-8")


def export_results(db: str, output_dir: str = "runs/reports",
                   objects_dir: str = "runs/objects",
                   books_dir: str | None = "books") -> dict[str, Any]:
    db_path = Path(db)
    report_dir = Path(output_dir)
    objects_path = Path(objects_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    states = _collect_states(db_path)
    pair_rows = _load_pair_rows(objects_path, states)
    source_rels: dict[str, str] = {}
    for state in states:
        image_base = state.get("image_base")
        fileref = state.get("fileref")
        if not image_base or not fileref:
            continue
        source_path = Path(image_base) / fileref
        source_rels[str(state.get("figure_id", ""))] = Path(
            os.path.relpath(source_path, report_dir)
        ).as_posix()
    s1_violations = _load_s1_violations(Path(books_dir), states) if books_dir else []
    status_counts = dict(sorted(Counter(s.get("status", "UNKNOWN") for s in states).items()))
    s1_reason_counts = dict(sorted(Counter(
        v.rsplit("|", 1)[-1] for v in s1_violations
    ).items()))

    json_path = report_dir / "results-summary.json"
    figures_csv = report_dir / "figures.csv"
    pairs_csv = report_dir / "pairs.csv"
    s1_csv = report_dir / "s1-violations.csv"
    dashboard = report_dir / "dashboard.html"

    summary = {
        "database": str(db_path),
        "objects_dir": str(objects_path),
        "figures": len(states),
        "pairs": len(pair_rows),
        "status_counts": status_counts,
        "s1_violation_counts": s1_reason_counts,
        "states": states,
    }
    _write_json(json_path, summary)
    _write_csv(figures_csv, [{
        "figure_id": s.get("figure_id", ""),
        "book_id": s.get("book_id", ""),
        "status": s.get("status", ""),
        "exclude_reason": s.get("exclude_reason") or "",
        "image_type": s.get("image_type") or "",
        "case_type": s.get("case_type") or "",
        "alarms": ";".join(s.get("alarms") or []),
        "pair_count": len(s.get("pair_records") or []),
        "qc_verdict": (s.get("qc_report") or {}).get("qc_verdict", ""),
        "caption": s.get("caption") or "",
    } for s in states])
    _write_csv(pairs_csv, pair_rows)
    _write_csv(s1_csv, [{
        "figure_id": v.split("|", 1)[0],
        "fileref": v.rsplit("|", 1)[0].split("|", 1)[-1],
        "reason": v.rsplit("|", 1)[-1],
    } for v in s1_violations])
    _render_html(dashboard, states, pair_rows, objects_path, s1_violations, source_rels)

    return {
        "dashboard": str(dashboard),
        "json": str(json_path),
        "figures_csv": str(figures_csv),
        "pairs_csv": str(pairs_csv),
        "s1_violations_csv": str(s1_csv),
        "figures": len(states),
        "pairs": len(pair_rows),
        "status_counts": status_counts,
        "s1_violation_counts": s1_reason_counts,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="runs/checkpoints-wanzi-full.sqlite3")
    ap.add_argument("--output-dir", default="runs/reports")
    ap.add_argument("--objects-dir", default="runs/objects")
    ap.add_argument("--books-dir", default="books")
    args = ap.parse_args()
    result = export_results(args.db, args.output_dir, args.objects_dir, args.books_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

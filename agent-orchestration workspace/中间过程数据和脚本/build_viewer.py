"""Build an offline HTML viewer for one finished book run.

Data comes from books/<book>/data.xml, runs/<run>/pairs.jsonl and the published
PNGs.  The page is written into the run directory so relative links work:

    runs/book_wanzhou/viewer.html
    pairs/<name>.png
    ../../books/万州瓦子坪/media/image9.jpg

Usage:
    python build_viewer.py --book 万州瓦子坪 --run runs/book_wanzhou
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from collections import Counter
from pathlib import Path

from archaeopairs.classify import classify
from archaeopairs.ingest.xml import parse_book
from archaeopairs.naming import extract_fig_number

ROOT = Path(__file__).resolve().parents[2]


def _rel(target: Path, base: Path) -> str:
    return os.path.relpath(target, base).replace("\\", "/")


def _num(figure_id: str) -> int:
    match = re.search(r"(\d+)$", figure_id)
    return int(match.group(1)) if match else 10**9


def _text(value) -> str:
    return "" if value is None else str(value)


def build(book: str, run_dir: Path) -> dict:
    book_dir = ROOT / "books" / book
    figures = parse_book(book_dir / "data.xml", book)
    media = {}
    for path in (book_dir / "media").iterdir():
        if path.is_file():
            media[path.stem] = path

    pairs_path = run_dir / "pairs.jsonl"
    rows = [json.loads(line) for line in
            pairs_path.read_text(encoding="utf-8").splitlines()]
    by_figure: dict[str, list[dict]] = {}
    for row in rows:
        by_figure.setdefault(row.get("figure_id", ""), []).append(row)

    viewer_dir = run_dir
    out: list[dict] = []
    line_counts = Counter()
    type_counts = Counter()
    pair_line_counts = Counter()
    status_counts = Counter()
    for fig in figures:
        image_type, work_line = classify(fig.caption, fig.figure_note, fig.media_path)
        line_counts[work_line.value] += 1
        type_counts[image_type.value] += 1
        fig_pairs = by_figure.get(fig.figure_id, [])
        stem = Path(fig.fileref).stem
        media_path = media.get(stem) or Path(fig.media_path)
        pairs = []
        for row in fig_pairs:
            mapping = ((row.get("provenance") or {}).get("mapping") or {})
            status_counts[row.get("status", "")] += 1
            pair_line_counts[mapping.get("line", work_line.value)] += 1
            rel = _text(row.get("image_path"))
            crop = rel if rel and (viewer_dir / rel).is_file() else ""
            pairs.append({
                "artifact_id": row.get("artifact_id") or "",
                "artifact_name": row.get("artifact_name"),
                "status": row.get("status") or "",
                "flags": row.get("quality_flags") or [],
                "image": crop,
                "description": row.get("description_text") or "",
                "text_length": row.get("text_length") or 0,
                "seq_ids": mapping.get("seq_ids") or [],
                "view_ids": mapping.get("view_ids") or [],
                "scale_ids": mapping.get("scale_ids") or [],
                "scale_sources": mapping.get("scale_sources") or [],
                "art_source": (row.get("provenance") or {}).get("art_source"),
                "source_para_ids": (row.get("provenance") or {}).get("source_para_ids") or [],
            })
        if pairs:
            pairs.sort(key=lambda p: (
                min([int(s) for s in p["seq_ids"] if str(s).isdigit()] or [9999]),
                p["artifact_id"]))
            figure_status = ("output" if any(p["status"] == "output" for p in pairs)
                             and not any(p["status"] == "review" for p in pairs)
                             else "pending_review")
        elif work_line.value == "archive":
            figure_status = "excluded"
        else:
            figure_status = "pending_review"
        out.append({
            "id": fig.figure_id,
            "stem": stem,
            "number": extract_fig_number(fig.caption, fallback=stem),
            "caption": fig.caption or "",
            "note": fig.figure_note or "",
            "image_type": image_type.value,
            "line": work_line.value,
            "status": figure_status,
            "exclude_reason": ("multi_plate_artifact" if image_type.value == "multi_plate_artifact"
                               else "discarded" if image_type.value == "discarded" else None),
            "original": _rel(media_path, viewer_dir) if media_path.exists() else "",
            "pairs": pairs,
        })

    out.sort(key=lambda item: _num(item["id"]))
    demo_path = ROOT / "runs" / "diag_l2" / "sample.json"
    l2_demo = json.loads(demo_path.read_text(encoding="utf-8")) if demo_path.is_file() else None
    return {
        "book": book,
        "run": run_dir.name,
        "figures": out,
        "l2_demo": l2_demo,
        "stats": {
            "figures": len(out),
            "pairs": len(rows),
            "output": status_counts.get("output", 0),
            "review": status_counts.get("review", 0),
            "line_figures": dict(line_counts),
            "line_pairs": dict(pair_line_counts),
            "types": dict(type_counts),
        },
    }


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f4f1ea; --panel:#fffdf8; --ink:#1f2a2c; --muted:#687477;
  --line:#d9d3c6; --accent:#0f6b60; --accent2:#b4552f;
  --green:#1d7a4c; --orange:#b07a1d; --red:#a63b2d; --gray:#7c8587;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 "Noto Sans SC","Microsoft YaHei",system-ui,sans-serif}
header{padding:28px 32px 20px;background:
  radial-gradient(900px 260px at 8% -20%,#dcebe4 0%,transparent 70%),
  linear-gradient(120deg,#102f2c,#17453f 60%,#1d544b);
  color:#f7f4ec;border-bottom:4px solid #c8a96b}
h1{margin:0 0 6px;font-size:30px;letter-spacing:.04em}
.sub{color:#d5e6df;max-width:1000px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
.stat{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.22);
  border-radius:10px;padding:8px 14px;min-width:106px}
.stat b{display:block;font-size:22px;line-height:1.2}
.stat span{font-size:12px;color:#cfe4dd}
nav{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:6px;
  padding:10px 24px;background:#fbf8f1;border-bottom:1px solid var(--line)}
nav button{border:1px solid var(--line);background:#fff;color:var(--ink);
  border-radius:999px;padding:8px 14px;cursor:pointer;font:inherit}
nav button.active{background:var(--accent);border-color:var(--accent);color:#fff}
nav .search{margin-left:auto;display:flex;align-items:center;gap:8px}
nav input{border:1px solid var(--line);border-radius:999px;padding:8px 14px;
  min-width:240px;font:inherit;background:#fff}
main{max-width:1500px;margin:0 auto;padding:22px 24px 80px}
.tab{display:none}.tab.active{display:block}
.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.route{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:18px;box-shadow:0 2px 0 rgba(30,40,40,.03)}
.route h3{margin:0 0 6px;font-size:17px}
.route .n{font-size:26px;color:var(--accent);font-weight:700}
.route p{color:var(--muted);margin:6px 0 0;font-size:13.5px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:18px 0;color:var(--muted);font-size:13px}
.chip{display:inline-flex;align-items:center;gap:5px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.figure{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  margin:16px 0;padding:16px;scroll-margin-top:90px}
.fig-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;
  border-bottom:1px dashed var(--line);padding-bottom:10px;margin-bottom:12px}
.fig-no{font-size:20px;font-weight:700;color:var(--accent)}
.caption{color:#33413f}
.note{color:var(--muted);font-size:13px;margin:-4px 0 12px;white-space:pre-wrap}
.badge{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:2px 9px;color:var(--muted)}
.status{font-size:12px;border-radius:999px;padding:2px 9px;color:#fff}
.s-output{background:var(--green)}.s-pending_review{background:var(--orange)}
.s-excluded{background:var(--gray)}.s-review{background:var(--orange)}
.fig-body{display:grid;grid-template-columns:minmax(220px,34%) 1fr;gap:16px}
@media(max-width:900px){.fig-body{grid-template-columns:1fr}}
.original{background:#f8f6f0;border:1px solid var(--line);border-radius:12px;
  padding:10px;align-self:start}
.original img{width:100%;max-height:420px;object-fit:contain;background:#fff;
  border-radius:8px;cursor:zoom-in}
.original .label{font-size:12px;color:var(--muted);margin-top:6px;word-break:normal;overflow-wrap:anywhere}
.pairs{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.pair{border:1px solid var(--line);border-radius:12px;overflow:hidden;
  display:flex;flex-direction:column;background:#fff}
.pair-media{background:#f7f4ed;display:flex;align-items:center;justify-content:center;
  min-height:120px;padding:8px}
.pair-media img{max-width:100%;max-height:260px;object-fit:contain;cursor:zoom-in}
.placeholder{color:var(--gray);font-size:13px;text-align:center;padding:26px 10px;
  border:1px dashed var(--line);border-radius:8px;margin:8px;width:100%}
.pair-info{padding:11px 12px 13px;display:flex;flex-direction:column;gap:7px}
.artifact{font-weight:700;font-size:16px}
.artifact small{font-weight:400;color:var(--muted);margin-left:6px}
.meta{font-size:12px;color:var(--muted);word-break:normal;overflow-wrap:anywhere}
.flags{display:flex;flex-wrap:wrap;gap:5px}
.flag{font-size:11px;border-radius:999px;padding:2px 7px;background:#eef1ee;
  color:#58635f;border:1px solid #dde2dd}
.flag.warn{background:#fdf1de;border-color:#efd7ae;color:#865d18}
.desc{font-size:13px;line-height:1.65;white-space:pre-wrap;max-height:11em;
  overflow:auto;border-top:1px solid #eee8dc;padding-top:7px}
.desc.empty{color:var(--gray);font-style:italic;max-height:none}
.empty-state{background:var(--panel);border:1px dashed var(--line);border-radius:16px;
  padding:40px;text-align:center;color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#efe9dd;font-size:13px;color:#4c5856}
td img{width:92px;height:66px;object-fit:contain;background:#fff;border-radius:6px;cursor:zoom-in}
.modal{position:fixed;inset:0;background:rgba(10,18,18,.86);display:none;
  align-items:center;justify-content:center;z-index:50;padding:24px}
.modal.open{display:flex}
.modal img{max-width:94vw;max-height:90vh;background:#fff;border-radius:8px}
.modal .close{position:absolute;top:18px;right:24px;color:#fff;font-size:34px;cursor:pointer}
.hidden{display:none!important}
footer{color:var(--muted);font-size:12px;padding:0 24px 30px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>__BOOK__ · 图文 Pair 结果</h1>
  <div class="sub">四条工作线 · 原图与单器物成图对照 · 序号/器物号/比例尺映射 · 正文描述</div>
  <div class="stats" id="stats"></div>
</header>
<nav id="tabs"></nav>
<main>
  <section class="tab active" id="tab-overview">
    <div class="overview-grid" id="routes"></div>
    <div class="legend" id="legend"></div>
    <p class="meta">说明：L1/L2/L3 的 Pair 卡片展示正文描述；L4 仅归档，不产 Pair。复核项保留成图（若有）并标注原因；无成图的复核项显示占位。</p>
  </section>
  <section class="tab" id="tab-multi_line"><div id="list-multi_line"></div></section>
  <section class="tab" id="tab-single_line"><div id="list-single_line"></div></section>
  <section class="tab" id="tab-single_plate"><div id="list-single_plate"></div></section>
  <section class="tab" id="tab-archive"><div id="list-archive"></div></section>
</main>
<div class="modal" id="modal"><span class="close">×</span><img alt=""></div>
<footer>ArchaeoPairs · __BOOK__ · 数据目录 __RUN__</footer>
<script>
const DATA = __DATA__;
const $ = (sel, root=document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LINE_NAME = {multi_line:"L1 多器物线图", single_line:"L2 单器物线图", single_plate:"L3 单器物版图", archive:"L4 归档"};
const LINE_DESC = {
  multi_line:"分割多器物线图 → 单器物组合 → 绑定比例尺；建立器物 ↔ 图中序号 ↔ 器物号映射。",
  single_line:"整图即单器物线图，不分割；序号段固定 01，按整图规格输出。",
  single_plate:"整图即单器物版图，不分割；序号段固定 01，输出整图。",
  archive:"多版图/弃用图，不产 Pair；保留原图与归档原因。"
};

function statusLabel(status){
  return {output:"output · 已产出", pending_review:"pending_review · 待复核", excluded:"excluded · 归档", review:"review · 复核"}[status] || status;
}
function statusClass(status){ return "s-" + (status || "excluded"); }
function flags(list){
  return (list || []).map(f => `<span class="flag ${f==='no_text'||f==='no_scale'||f==='qc_reject'?'warn':''}">${esc(f)}</span>`).join("");
}
function img(src, alt){
  if(!src) return "";
  return `<img src="${esc(src)}" alt="${esc(alt)}" loading="lazy" onclick="openModal(this.src, this.alt)">`;
}
function pairCard(p){
  const media = p.image
    ? `<div class="pair-media">${img(p.image, p.artifact_id)}</div>`
    : `<div class="pair-media"><div class="placeholder">无成图（${esc(statusLabel(p.status))}）</div></div>`;
  const desc = p.description
    ? `<div class="desc">${esc(p.description)}</div>`
    : `<div class="desc empty">无正文描述（${esc((p.flags||[]).includes("no_text") ? "no_text" : "未匹配到正文")}）</div>`;
  const seq = (p.seq_ids||[]).join(", ") || "—";
  const views = (p.view_ids||[]).join(", ") || "—";
  const scales = (p.scale_ids||[]).length
    ? `${(p.scale_ids||[]).join(", ")}（${(p.scale_sources||[]).join(", ") || "unknown"}）`
    : "未绑定";
  return `<div class="pair">
    ${media}
    <div class="pair-info">
      <div class="artifact">${esc(p.artifact_id)}${p.artifact_name ? `<small>${esc(p.artifact_name)}</small>` : ""}</div>
      <div class="meta">图中序号 ${esc(seq)} · 视图 ${esc(views)} · 比例尺 ${esc(scales)}</div>
      <div class="meta">状态 ${esc(statusLabel(p.status))} · 文本 ${p.text_length || 0} 字${p.art_source ? ` · 来源 ${esc(p.art_source)}` : ""}</div>
      <div class="flags">${flags(p.flags)}</div>
      ${desc}
    </div>
  </div>`;
}
function figureCard(f){
  const pairs = f.pairs.length
    ? f.pairs.map(pairCard).join("")
    : `<div class="placeholder">该图没有 Pair（${esc(statusLabel(f.status))}）</div>`;
  const search = [f.id, f.number, f.caption, f.note, f.status,
    ...f.pairs.map(p => `${p.artifact_id} ${p.artifact_name||""} ${p.description||""}`)].join(" ");
  return `<article class="figure" data-search="${esc(search.toLowerCase())}">
    <div class="fig-head">
      <span class="fig-no">${esc(f.number)}</span>
      <span class="badge">${esc(LINE_NAME[f.line] || f.line)}</span>
      <span class="status ${statusClass(f.status)}">${esc(statusLabel(f.status))}</span>
      <span class="caption">${esc(f.caption)}</span>
      <span class="badge">${esc(f.id)}</span>
    </div>
    ${f.note ? `<div class="note">图注：${esc(f.note)}</div>` : ""}
    <div class="fig-body">
      <div class="original">
        ${img(f.original, f.number)}
        <div class="label">原图：${esc(f.original || "缺失")}</div>
      </div>
      <div class="pairs">${pairs}</div>
    </div>
  </article>`;
}
function archiveTable(figs){
  if(!figs.length) return `<div class="empty-state">本书没有 L4 归档图。</div>`;
  const rows = figs.map(f => `<tr data-search="${esc((f.id+" "+f.caption+" "+(f.exclude_reason||"")).toLowerCase())}">
    <td>${img(f.original, f.number)}</td>
    <td><b>${esc(f.number)}</b><br><span class="meta">${esc(f.id)}</span></td>
    <td>${esc(f.caption || "—")}</td>
    <td>${esc(f.exclude_reason || f.image_type)}</td>
  </tr>`).join("");
  return `<table><thead><tr><th>原图</th><th>图号</th><th>图题</th><th>归档原因</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function render(){
  const s = DATA.stats;
  $("#stats").innerHTML = [
    ["图", s.figures], ["Pair", s.pairs], ["output", s.output], ["review", s.review],
    ["L1 图", s.line_figures.multi_line||0], ["L2 图", s.line_figures.single_line||0],
    ["L3 图", s.line_figures.single_plate||0], ["L4 图", s.line_figures.archive||0]
  ].map(([k,v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join("");

  const routes = ["multi_line","single_line","single_plate","archive"].map(line => {
    const n = s.line_figures[line] || 0;
    const pn = s.line_pairs[line] || 0;
    return `<div class="route"><h3>${LINE_NAME[line]}</h3><div class="n">${n} 图</div>
      <p>${LINE_DESC[line]}</p><p>Pair：${pn}</p></div>`;
  }).join("");
  $("#routes").innerHTML = routes;
  $("#legend").innerHTML = `
    <span class="chip"><i class="dot" style="background:var(--green)"></i>output 已产出</span>
    <span class="chip"><i class="dot" style="background:var(--orange)"></i>review 待复核</span>
    <span class="chip"><i class="dot" style="background:var(--gray)"></i>excluded 归档</span>
    <span class="chip">复核原因：no_text / no_scale / qc_reject 等</span>`;

  const tabs = [["overview","概览",null],
    ["multi_line",`L1 多器物线图（${s.line_figures.multi_line||0}）`,"multi_line"],
    ["single_line",`L2 单器物线图（${s.line_figures.single_line||0}）`,"single_line"],
    ["single_plate",`L3 单器物版图（${s.line_figures.single_plate||0}）`,"single_plate"],
    ["archive",`L4 归档（${s.line_figures.archive||0}）`,"archive"]];
  $("#tabs").innerHTML = tabs.map(([id,label,line],i) =>
    `<button data-tab="${id}" class="${i===0?'active':''}">${esc(label)}</button>`).join("")
    + `<div class="search"><input id="q" placeholder="搜索器物号 / 图号 / 正文…"></div>`;

  for(const line of ["multi_line","single_line","single_plate"]){
    const figs = DATA.figures.filter(f => f.line === line);
    const box = $("#list-"+line);
    if(!figs.length){
      const demo = DATA.l2_demo;
      const demoCard = demo ? figureCard({
        id: demo.figure_id, number: demo.figure_number || "图六一",
        caption: demo.caption, note: demo.note, line: "single_line",
        status: demo.status, original: demo.original,
        pairs: [{
          artifact_id: demo.artifact_id, artifact_name: demo.artifact_name,
          status: demo.status, flags: demo.flags, image: demo.image,
          description: demo.description, text_length: demo.text_length,
          seq_ids: demo.seq_ids, view_ids: demo.view_ids,
          scale_ids: demo.scale_ids, scale_sources: demo.scale_sources,
          art_source: "figure_note", source_para_ids: []
        }]
      }) : "";
      box.innerHTML = `<div class="empty-state"><b>本书没有 ${LINE_NAME[line]} 的图。</b><br>
        ${line==="single_line" ? "万州瓦子坪的分类结果为 0 张单器物线图；下面补一张同管线的跨书 L2 样例，便于查看整图直通与正文。" : "该线没有产出。"}</div>
        ${line==="single_line" && demo ? `<div class="note" style="margin:14px 0 0">跨书 L2 示例（非万州内容）：${esc(demo.book)} · ${esc(demo.figure_id)}</div>` + demoCard : ""}`;
    } else {
      box.innerHTML = figs.map(figureCard).join("");
    }
  }
  $("#list-archive").innerHTML = archiveTable(DATA.figures.filter(f => f.line === "archive"));

  document.querySelectorAll("nav button[data-tab]").forEach(btn => {
    btn.onclick = () => activateTab(btn.dataset.tab);
  });
  $("#q").oninput = filter;
  const initial = (location.hash || "").replace(/^#/, "");
  if(initial && document.getElementById("tab-"+initial)) activateTab(initial, false);
}
function activateTab(id, updateHash=true){
  document.querySelectorAll("nav button[data-tab]").forEach(b=>b.classList.toggle("active", b.dataset.tab===id));
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active", t.id==="tab-"+id));
  if(updateHash) history.replaceState(null, "", "#"+id);
  filter();
}
function filter(){
  const q = ($("#q")?.value || "").trim().toLowerCase();
  document.querySelectorAll(".figure, tbody tr[data-search]").forEach(el => {
    el.classList.toggle("hidden", q && !el.dataset.search.includes(q));
  });
}
function openModal(src, alt){
  const m = $("#modal");
  m.querySelector("img").src = src; m.querySelector("img").alt = alt || "";
  m.classList.add("open");
}
$("#modal").onclick = (e) => { if(e.target.id === "modal" || e.target.classList.contains("close")) $("#modal").classList.remove("open"); };
document.addEventListener("keydown", e => { if(e.key === "Escape") $("#modal").classList.remove("open"); });
render();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", default="万州瓦子坪")
    parser.add_argument("--run", default="runs/book_wanzhou")
    args = parser.parse_args(argv)
    run_dir = (ROOT / args.run).resolve()
    if not (run_dir / "pairs.jsonl").is_file():
        raise SystemExit(f"missing {run_dir/'pairs.jsonl'}")
    data = build(args.book, run_dir)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    title = f"{args.book} · 图文 Pair 展示"
    page = (TEMPLATE.replace("__TITLE__", html.escape(title))
            .replace("__BOOK__", html.escape(args.book))
            .replace("__RUN__", html.escape(run_dir.name))
            .replace("__DATA__", payload))
    target = run_dir / "viewer.html"
    target.write_text(page, encoding="utf-8")
    print(json.dumps({"viewer": str(target), "figures": len(data["figures"]),
                      "pairs": data["stats"]["pairs"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
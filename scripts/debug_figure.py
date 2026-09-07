"""单图全流程调试：跑通万州瓦子坪指定图，打印逐节点状态与产物。

用法: .venv/Scripts/python.exe -X utf8 scripts/debug_figure.py [figure_id] [--vl]
缺省 image9（多器物线图）。--vl 开启 VL 三态仲裁（需 .env VOLCENGINE_API_KEY）。
"""
import sys
import uuid
from pathlib import Path

from archaeopairs.agents import s3 as s3_agent
from archaeopairs.capability.factory import build_services
from archaeopairs.config import load_flags, load_providers, load_thresholds
from archaeopairs import naming
from archaeopairs.orchestration import build_graph
from archaeopairs.parsers import s1_xml, s3_note
from archaeopairs.storage import LocalObjectStore

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
FIG = _args[0] if _args else "image9"
USE_VL = "--vl" in sys.argv
BOOK = "万州瓦子坪"

xml = next(Path("books").joinpath(BOOK).rglob("data.xml"))
figures, ground, _ = s1_xml.parse_report(xml, BOOK)
body_paras = s1_xml.parse_body(xml)
fig = next(f for f in figures if f.figure_id.endswith(FIG))
print(f"figure={fig.figure_id} caption={fig.caption!r}")
print(f"note={fig.figure_note!r}")

providers = load_providers().model_copy(update={
    "sam": "cv", "ocr": "paddle", "compositor": "pixel",
    "vl": "ark" if USE_VL else "mock"})
store = LocalObjectStore("runs/objects")
svc = build_services(ground=ground, thresholds=load_thresholds(),
                     flags=load_flags(), providers=providers,
                     object_store=store, vl_enabled=USE_VL)
print("vl_arbiter:", "on" if svc.vl_arbiter is not None else "off (纯 CV)")

note_items = s3_note.parse_note(fig.figure_note or "")
note_arts = {a for it in note_items for a in it.artifact_ids}
caption_arts = [] if note_arts else s3_note.extract_caption_artifacts(fig.caption)
fig_number = naming.extract_fig_number(fig.caption)
paras = s3_agent.select_paras(body_paras, note_arts | set(caption_arts), fig_number)

init = {
    "book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
    "caption": fig.caption, "figure_note": fig.figure_note,
    "book_has_artifact": True, "image_base": str(xml.parent),
    "body_paras": paras, "assembled": False,
    "trace_id": str(uuid.uuid4()), "flags": load_flags().model_dump(),
    "status": "INIT",
}
app = build_graph(svc)
result = app.invoke(init, config={"configurable": {"thread_id": f"debug:{FIG}"}})

print("\n--- 结果 ---")
for k in ("image_type", "case_type", "status", "alarms", "confidence",
          "degraded"):
    print(f"{k}: {result.get(k)}")
print("note_items:", result.get("note_items"))
print("seq_annotations:", result.get("seq_annotations"))
print("scale_annotations:", result.get("scale_annotations"))
print("vision_units:", bool(result.get("vision_units")),
      "| view_groups:", len(result.get("view_groups") or []))
for g in result.get("view_groups") or []:
    print(f"  group {g['group_id']}: masks={g['mask_idxs']} seqs={g['seq_ids']} "
          f"scales={g['scale_sis']} render={'Y' if g.get('render') else 'N'}")
print("atom_masks:", len(result.get("atom_masks") or []))
print("fused:", result.get("fused"))
print("qc_report:", result.get("qc_report"))
print("pair_records:")
for r in result.get("pair_records") or []:
    print(" ", r["image_path"], "|", r["artifact_id"], "|",
          r.get("provenance", {}).get("views"), "views")
    p = Path("runs/objects") / r["image_path"]
    if p.exists():
        print("    PNG:", p, p.stat().st_size, "bytes")

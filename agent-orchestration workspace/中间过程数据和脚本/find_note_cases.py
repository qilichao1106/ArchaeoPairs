"""按位置对应规则统计图注映射形态，并输出真实样例。"""
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path("v1/src").resolve()))
from archaeopairs.parsers import s3_note  # noqa: E402

cases = {"1seq_Nart": [], "Nseq_1art_item": [], "Nseq_1art_cross": [],
         "Nseq_Nart_range": [], "Nseq_Nart_group": []}
for xml_path in sorted(Path("books").glob("*/data.xml")):
    book = xml_path.parent.name
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        continue
    for el in root.iter():
        if el.tag.split("}")[-1] != "figure-note":
            continue
        text = "".join(el.itertext()).strip()
        if not text:
            continue
        try:
            items = s3_note.parse_note(text)
        except Exception:
            continue
        pairs = []
        art_seqs = defaultdict(set)
        for it in items:
            seqs = list(it.seq_list or ([int(it.seq)] if str(it.seq).isdigit() else []))
            arts = list(dict.fromkeys(it.artifact_ids))
            if not seqs or not arts:
                continue
            if len(seqs) == 1:
                zipped = [(seqs[0], a) for a in arts]
            elif len(arts) == 1:
                zipped = [(s, arts[0]) for s in seqs]
            elif len(seqs) == len(arts):
                zipped = list(zip(seqs, arts))
            else:
                continue
            pairs.extend(zipped)
            for s, a in zipped:
                art_seqs[a].add(s)
            if len(seqs) == 1 and len(arts) > 1:
                cases["1seq_Nart"].append((book, text, it.model_dump(), zipped))
            elif len(seqs) > 1 and len(arts) == 1:
                cases["Nseq_1art_item"].append((book, text, it.model_dump()))
            elif len(seqs) > 1 and len(arts) > 1 and len(seqs) == len(arts):
                key = "Nseq_Nart_range" if ("~" in it.seq or "～" in it.seq) else "Nseq_Nart_group"
                cases[key].append((book, text, it.model_dump(), zipped))
        for a, seqs in art_seqs.items():
            if len(seqs) > 1:
                cases["Nseq_1art_cross"].append((book, text, a, sorted(seqs)))
                break

for key, rows in cases.items():
    print(f"\n===== {key}: {len(rows)} =====")
    for row in rows[:4]:
        print(row)

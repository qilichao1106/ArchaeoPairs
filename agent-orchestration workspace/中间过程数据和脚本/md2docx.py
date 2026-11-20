"""极简 Markdown → DOCX（标题/表格/列表/代码块/引用），用于方案文档交付。"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt


def set_font(run, name="微软雅黑", size=None, bold=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def strip_md(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def add_table(doc, rows):
    if len(rows) < 2:
        return
    cols = len(rows[0])
    t = doc.add_table(rows=len(rows), cols=cols)
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        for j in range(cols):
            cell = t.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(strip_md(row[j] if j < len(row) else ""))
            set_font(run, size=9, bold=(i == 0))


def convert(src: Path, dst: Path):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    lines = src.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip() or line.strip() == "---":
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            for c in code:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                set_font(p.add_run(c), name="Consolas", size=8.5)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            p = doc.add_heading(level=min(level, 4))
            set_font(p.add_run(strip_md(m.group(2))), size={1: 18, 2: 14, 3: 12, 4: 11}[level], bold=True)
            i += 1
            continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            add_table(doc, rows)
            continue
        if line.lstrip().startswith(("- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            set_font(p.add_run(strip_md(line.lstrip()[2:])))
            i += 1
            continue
        if line.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            set_font(p.add_run(strip_md(line.lstrip("> "))), size=9.5)
            i += 1
            continue
        p = doc.add_paragraph()
        set_font(p.add_run(strip_md(line)))
        i += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))
    print(dst)


if __name__ == "__main__":
    convert(Path(sys.argv[1]), Path(sys.argv[2]))

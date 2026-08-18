"""V0.4 结构符合度审计：对 books 每书 data.xml 依《V0.4》§2.1/§2.4 契约评分排序。

V0.4 标准型契约（第一章/第二章优先）：
  标准型 = caption role="figure-title" + para role="figure-note" 完整（§2.1）
  主链解析 = figure 与其后紧邻 figure-note 关联（§2.4）
题干契约 = caption 角色完整 / note 角色正确 / media 有 fileref 与像素尺寸（§1.4）
"""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'src')
import xml.etree.ElementTree as ET
from archaeopairs.parsers import s1_xml
from archaeopairs.parsers.s3_note import ARTIFACT_RE, normalize, colon_norm

def arts(t):
    n = normalize(t or '')
    return [colon_norm(n[m.start():m.end()]) for m in ARTIFACT_RE.finditer(n)]

def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]

def analyze(path):
    tree = ET.parse(path); root = tree.getroot(); strip_ns(root)
    figures = [el for el in root.iter('figure')]
    nfig = len(figures)
    # caption 统计
    cap_total = cap_role = 0
    for f in figures:
        cap = f.find(".//caption[@role='figure-title']")
        if cap is not None and ''.join(cap.itertext()).strip(): cap_role += 1
        for c in f.iter('caption'):
            if ''.join(c.itertext()).strip():
                cap_total += 1
                break
    # note para 统计（任意位置）
    note_total = 0; note_role = 0; note_after_fig = 0
    paras = [el for el in root.iter('para')]
    for p in paras:
        if p.get('role') == 'figure-note' and ''.join(p.itertext()).strip():
            note_role += 1
    note_total = note_role  # 以此为准
    # 后紧邻 figure-note（§2.4 主链）：figure 后最近的 para 是 figure-note？
    for f in figures:
        parent = None
        for el in root.iter():
            if el is f: break
            parent = el
        # 简化：用 parse_report 的 figure_note 命中（关联成功的比例）
    # 用 s1_xml 关联结果
    figs, _, viol = s1_xml.parse_report(path, 'x')
    with_note = sum(1 for f in figs if f.figure_note)
    with_cap = sum(1 for f in figs if f.caption)
    both = sum(1 for f in figs if f.caption and f.figure_note)
    # media 像素契约
    im = sum(1 for el in root.iter('imagedata'))
    im_fileref = sum(1 for el in root.iter('imagedata') if el.get('fileref'))
    im_dims = sum(1 for el in root.iter('imagedata') if (el.get('contentwidth') or '').strip()
                  and (el.get('contentdepth') or '').strip())
    return dict(nfig=nfig, cap_role=cap_role, cap_total=cap_total, note=note_role,
                rel_note=with_note, rel_cap=with_cap, both=both,
                im=im, im_fr=im_fileref, im_dims=im_dims, viol=len(viol), nfig_s1=len(figs))

def score(r):
    """符合度分数(0-100)：标题契约 + 关联 + 像素 + 违约加权。"""
    s = 0.0
    if r['nfig']:
        s += 20 * (r['cap_role'] / r['nfig'])                      # 图题角色率
        s += 20 * (r['note'] / max(r['nfig'], 1)) * (r['note'] > 0)  # 图注存在率
        s += 15 * (r['rel_note'] / r['nfig'])                      # 后紧邻关联命中
        s += 15 * (r['both'] / r['nfig'])                          # 题注双全(标准型)
        s += 10 * (r['rel_cap'] / r['nfig'])                       # 图题可达
        s += 10 * (r['im_dims'] / max(r['im'], 1))
        s -= 5 * (r['viol'] / max(r['nfig'], 1))
    return round(max(0, s), 1)

def main():
    books = sorted(os.listdir('books'))
    rows = []
    for b in books:
        p = None
        for root, _, fs in os.walk(os.path.join('books', b)):
            if 'data.xml' in fs: p = os.path.join(root, 'data.xml'); break
        if not p:
            rows.append((b, None)); continue
        r = analyze(p); r['book'] = b; r['score'] = score(r); rows.append((b, r))
    headers = ['book','score','nfig','図題role','図注','关联命中','双全','imDims%','viol']
    print(f"{'book':<16}{'score':>6}{'nfig':>6}{'capRole%':>8}{'note%':>6}{'relNote%':>9}{'both%':>6}{'dim%':>6}{'viol':>6}")
    for b, r in sorted(rows, key=lambda x: x[1]['score'] if x[1] else -1, reverse=True):
        if not r:
            print(f"{b:<16}      NO XML"); continue
        print(f"{b:<16}{r['score']:>6}{r['nfig']:>6}{(100*r['cap_role']/r['nfig'] if r['nfig'] else 0):>8.0f}"
              f"{(100*r['note']/r['nfig'] if r['nfig'] else 0):>6.0f}"
              f"{(100*r['rel_note']/r['nfig'] if r['nfig'] else 0):>9.0f}"
              f"{(100*r['both']/r['nfig'] if r['nfig'] else 0):>6.0f}"
              f"{(100*r['im_dims']/max(r['im'],1)):>6.0f}{r['viol']:>6}")

if __name__ == '__main__':
    main()
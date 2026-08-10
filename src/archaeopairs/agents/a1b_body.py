# -*- coding: utf-8 -*-
"""A1b 正文NLP（链②）：按器物号切分正文，抽描述与图引用。

报告级 build_artifact_records() 由 BookIndexer 解析后的 body_paras 构建；
figure 级 Agent 按图号归一匹配引用，产出本 figure 的 id_to_desc 与 refs。

切分思路：正文描述段形如"器物名 器物号：N，……（图X，N）"。以器物号出现位置为
锚点做 lookahead 切段——每段归属于其内首个器物号，直至下一器物号出现。
"""
from __future__ import annotations

import re

from ..agent import AgentInterface, AgentContext
from ..errors import ErrorCode
from ..regexes import (ARTIFACT_ID_RE, FIGURE_REF_RE, PLATE_REF_RE,
                       normalize_artifact_id, normalize_figure_no)
from ..state import PairState

# 器物名 器物号 的起始模式（如"陶纺轮 00FBH2:1"）：前缀为 2-8 个汉字的器类名
_HEAD_RE = re.compile(r"([一-龥]{1,8}?)[ 　]*(" + ARTIFACT_ID_RE.pattern + r")")


def build_artifact_records(body_paras: list) -> list[dict]:
    """报告级：从正文段落构建 artifact_records。

    切分思路：以器物号出现位置为锚点做 lookahead 切段——每段从器物号起、至下一
    器物号止，归属该器物号；段首的器类名（如"陶纺轮 00FBH2:1"）单独抽取。
    同一器物号多段描述合并（跨页续段）。
    """
    records: dict[str, dict] = {}
    order: list[str] = []
    for bp in body_paras:
        text, page = bp.text, bp.page
        matches = list(ARTIFACT_ID_RE.finditer(text))
        if not matches:
            continue
        for i, m in enumerate(matches):
            # 段范围：向前尝试纳入器类名（紧邻的 1-8 个汉字），向后至下一器物号
            head = _HEAD_RE.search(text, max(0, m.start() - 10), m.end())
            start = head.start() if head and head.group(2) == m.group(0) else m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            seg = text[start:end].strip()
            norm, original = normalize_artifact_id(m.group(0))
            refs = [(normalize_figure_no("图" + fn)[0], int(sn))
                    for fn, sn in FIGURE_REF_RE.findall(seg)]
            prefs = [(normalize_figure_no("图版" + fn)[0], int(sn))
                     for fn, sn in PLATE_REF_RE.findall(seg)]
            if norm not in records:
                records[norm] = {
                    "artifact_id": norm, "original_id": original,
                    "name": head.group(1) if head else "",
                    "description": seg,
                    "figure_refs": refs, "plate_refs": prefs, "page": page,
                }
                order.append(norm)
            else:                                   # 跨页/多段合并
                records[norm]["description"] += " " + seg
                records[norm]["figure_refs"] += refs
                records[norm]["plate_refs"] += prefs
    return [records[k] for k in order]


class A1bBodyNLP(AgentInterface):
    name = "A1b"
    timeout_s = 10
    prompt_deps = ["P-A1b"]
    output_fields = ["artifact_records"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        all_records: list[dict] = ctx.config.get("__artifact_records__", [])
        fig_no = state.figure_index.get("figure_no", {}).get("norm", "")

        # 本 figure 引用到的器物（链②：正文 (图X，N) ↔ 描述段器物号）
        hits = []
        for rec in all_records:
            seqs = [sn for fn, sn in rec["figure_refs"] if fn == fig_no]
            if seqs:
                hits.append({**rec, "ref_seqs": seqs})
        state.artifact_records = hits
        # 引用未命中（E_REF_NOFIGURE）在报告级汇总统计，figure 级不展开
        self.emit(state, "A1c", "artifact_records")
        return state

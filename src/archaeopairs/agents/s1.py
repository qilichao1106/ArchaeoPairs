"""S1 报告索引器（§4.1）。Node: 摄入契约校验 + 无器物号排除。

契约违约（caption 无 role/figure-title 缺失）→ E102 排除；无器物号信号 → 排除。
XML 解析与 ground 构建在驱动层（cli）完成，节点内做单图校验。
"""
from __future__ import annotations

from ..parsers.s3_note import ARTIFACT_RE, COMPONENT_RE
from . import Services


def _has_artifact_signal(state: dict) -> bool:
    blob = (state.get("figure_note") or "") + " ".join(
        p.get("text", "") for p in state.get("body_paras", [])
    )
    return bool(ARTIFACT_RE.search(blob) or COMPONENT_RE.search(blob))


def run(state: dict, svc: Services) -> dict:
    if state.get("caption") is None:
        return {"status": "EXCLUDED", "exclude_reason": "E102_contract_violation"}
    if not _has_artifact_signal(state):
        return {"status": "EXCLUDED", "exclude_reason": "no_artifact_id"}
    return {"status": "PARSED"}

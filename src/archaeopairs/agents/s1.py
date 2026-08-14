"""S1 报告索引器（§4.1）。Node: 摄入契约校验 + 无器物号排除。

契约违约（caption 无 role/figure-title 缺失）→ E102 排除；
无器物号信号（书级，由 CLI 解析后注入 book_has_artifact）→ 排除。
XML 解析与 ground 构建在驱动层（cli）完成，节点内做单图校验。
"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    if state.get("caption") is None:
        return {"status": "EXCLUDED", "exclude_reason": "E102_contract_violation"}
    if not state.get("book_has_artifact", True):
        return {"status": "EXCLUDED", "exclude_reason": "no_artifact_id"}
    return {"status": "PARSED"}

"""S1 报告索引器（§4.1）。Node: 书级器物号信号排除。

caption 缺失由 S1 XML 记为非阻断告警；附录版图等无图题记录继续进入 S2，
由图注和像素家族判定处理。无器物号信号（书级，由 CLI 解析后注入
book_has_artifact）→ 排除。
XML 解析与 ground 构建在驱动层（cli）完成，节点内做单图校验。
"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    if not state.get("book_has_artifact", True):
        return {"status": "EXCLUDED", "exclude_reason": "no_artifact_id"}
    return {"status": "PARSED"}

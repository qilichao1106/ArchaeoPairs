"""S1 报告索引器（§4.1）。Node: 校验/归一单图记录，置 PARSED。"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    return {"status": "PARSED"}

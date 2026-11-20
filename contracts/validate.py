#!/usr/bin/env python3
"""契约自检：JSON Schema metaschema + 样例实例校验（Orchestrator 维护）。

用法：python contracts/validate.py
退出 0 = 契约可用；1 = 校验失败。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
SCHEMAS = {
    "artifact_map": ROOT / "artifact_map.schema.json",
    "pair_record": ROOT / "pair_record.schema.json",
}

SAMPLE_MAP = {
    "schema_version": "1.0",
    "book_id": "万州余家河墓群",
    "figure_id": "image215",
    "line": "multi_line",
    "case_type": "rule_a",
    "units": [{
        "artifact_id": "M139:3",
        "artifact_name": "铜釜",
        "seq_ids": ["8"],
        "view_ids": [0],
        "group_ids": [0],
        "scale_bindings": [{
            "scale_id": 0, "source": "L2_unique_shared", "shared": True,
            "text": "8厘米", "value": 8.0, "unit": "厘米", "prefix_nos": [],
        }],
        "line": "multi_line", "case": "rule_a", "source": "figure_note",
        "confidence": 0.95, "whole_image": False, "status": "output", "evidence": {},
    }],
    "unbound_groups": [], "unbound_views": [], "unbound_seqs": [],
    "conflicts": [], "alarms": [], "status": "composed",
}

SAMPLE_PAIR = {
    "schema_version": "1.0",
    "book_id": "万州余家河墓群",
    "figure_id": "image215",
    "artifact_id": "M139:3",
    "artifact_name": "铜釜",
    "figure_number": "图二一二",
    "source_role": "line",
    "image_path": "图二一二_8_M139-3.png",
    "image_merge_mode": "line_only",
    "description_text": "铜釜 1件。标本M139：3……",
    "text_length": 18,
    "provenance": {
        "mapping": {
            "artifact_id": "M139:3", "seq_ids": ["8"], "view_ids": [0],
            "scale_ids": [0], "scale_sources": ["L2_unique_shared"],
            "confidence": 0.95, "line": "multi_line", "source_role": "line",
        },
        "shared_group": "g0",
    },
    "quality_flags": ["shared_image"],
    "status": "output",
}


def main() -> int:
    failed = 0
    for name, path in SCHEMAS.items():
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            print(f"[PASS] schema:{name}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] schema:{name} {exc}")
            continue
        sample = SAMPLE_MAP if name == "artifact_map" else SAMPLE_PAIR
        try:
            Draft202012Validator(schema).validate(sample)
            print(f"[PASS] sample:{name}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] sample:{name} {exc}")

    # 负向对照：缺必填字段必须失败
    schema = json.loads(SCHEMAS["pair_record"].read_text(encoding="utf-8"))
    broken = {k: v for k, v in SAMPLE_PAIR.items() if k != "artifact_id"}
    if Draft202012Validator(schema).is_valid(broken):
        failed += 1
        print("[FAIL] negative:pair_record missing artifact_id accepted")
    else:
        print("[PASS] negative:pair_record missing artifact_id rejected")

    print(f"\n{failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
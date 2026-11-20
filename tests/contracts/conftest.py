"""Shared fixtures for the frozen JSON Schema contract tests (T-001).

Tests locate the repository root relative to this file, never relative to the
current working directory, so the suite runs from the project root with:

    python -m pytest tests/contracts -q
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def load_schema(name):
    with (CONTRACTS_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def iter_errors(schema, instance):
    return list(Draft202012Validator(schema).iter_errors(instance))


def assert_valid(schema, instance):
    errors = iter_errors(schema, instance)
    assert errors == [], [error.message for error in errors]


def assert_invalid(schema, instance):
    errors = iter_errors(schema, instance)
    assert errors, "expected schema to reject the instance, but it validated"
    return errors





@pytest.fixture(scope="session")
def artifact_map_schema():
    return load_schema("artifact_map.schema.json")


@pytest.fixture(scope="session")
def pair_record_schema():
    return load_schema("pair_record.schema.json")


@pytest.fixture
def valid_artifact_map():
    return {
        "schema_version": "1.0",
        "book_id": "book-001",
        "figure_id": "fig-2-1-16",
        "line": "multi_line",
        "case_type": "rule_a",
        "units": [
            {
                "artifact_id": "M4-2",
                "artifact_name": "铜舟",
                "seq_ids": ["1"],
                "view_ids": [1],
                "group_ids": [0],
                "scale_bindings": [
                    {
                        "scale_id": 1,
                        "source": "L1_prefix",
                        "shared": False,
                        "text": "1:10",
                        "value": 10.0,
                        "unit": "cm",
                        "prefix_nos": ["1"],
                    }
                ],
                "line": "multi_line",
                "case": "rule_a",
                "source": "figure_note",
                "confidence": 0.95,
                "whole_image": False,
                "status": "output",
                "evidence": {"page": 12},
            }
        ],
        "unbound_groups": [{"group_id": 1, "reason": "no_seq"}],
        "unbound_views": [{"view_ids": [3], "reason": "no_seq"}],
        "unbound_seqs": [{"seq_id": "7", "reason": "unmapped_seq"}],
        "conflicts": ["seq 7 remapped"],
        "alarms": ["E001"],
        "status": "pending_review",
    }


@pytest.fixture
def valid_pair_record():
    return {
        "schema_version": "1.0",
        "book_id": "book-001",
        "figure_id": "fig-2-1-16",
        "artifact_id": "M4-2",
        "artifact_name": "铜舟",
        "figure_number": "图2-1-16",
        "source_role": "line",
        "image_path": "images/fig-2-1-16_line_M4-2.png",
        "candidate_images": [
            {
                "path": "images/fig-2-1-16_line.png",
                "role": "line",
                "source_figure_id": "fig-2-1-16",
                "confidence": 0.9,
            },
            {"path": "images/fig-2-1-16_plate.png", "role": "plate"},
        ],
        "image_merge_mode": "line_plus_plate",
        "description_text": "M4:2，铜舟，通高10厘米。",
        "text_length": 18,
        "provenance": {
            "mapping": {
                "artifact_id": "M4-2",
                "seq_ids": ["1"],
                "view_ids": [1],
                "scale_ids": [1],
                "scale_sources": ["L1_prefix"],
                "confidence": 0.9,
                "line": "multi_line",
                "source_role": "line",
            },
            "source_para_ids": ["p12"],
            "art_source": "text",
            "case": "rule_a",
            "shared_group": "g1",
        },
        "quality_flags": ["no_scale"],
        "status": "output",
    }
"""Frozen acceptance tests for the T-004 prompt contract (card section 3).

Each prompt must demand JSON only, forbid guessing, and expose the structure
the downstream parser expects.  These tests are textual contract checks, not
model-quality checks.
"""

from __future__ import annotations

from archaeopairs.vlm.prompts import OCR_PROMPT, QC_PROMPT, VISUAL_PROMPT


def test_ocr_prompt_demands_strict_json_with_the_three_result_lists():
    assert "JSON" in OCR_PROMPT
    for key in ("seqs", "scales", "texts"):
        assert f'"{key}"' in OCR_PROMPT
    assert "bbox" in OCR_PROMPT
    assert "猜测" in OCR_PROMPT
    assert "[]" in OCR_PROMPT


def test_visual_prompt_covers_classification_views_regions_and_scale_check():
    assert "JSON" in VISUAL_PROMPT
    for key in ("image_type", "views", "regions", "scale_check"):
        assert f'"{key}"' in VISUAL_PROMPT
    assert "猜测" in VISUAL_PROMPT
    assert "null" in VISUAL_PROMPT


def test_qc_prompt_covers_verdict_and_defects():
    assert "JSON" in QC_PROMPT
    for key in ("verdict", "defects", "needs_review"):
        assert f'"{key}"' in QC_PROMPT
    assert "猜测" in QC_PROMPT
    assert "null" in QC_PROMPT
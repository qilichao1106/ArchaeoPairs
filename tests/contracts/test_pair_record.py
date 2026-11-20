"""T-001: PairRecord positive cases, null text, required-field and enum rejections."""

import copy

from conftest import assert_invalid, assert_valid


def test_valid_pair_record_passes(pair_record_schema, valid_pair_record):
    assert_valid(pair_record_schema, valid_pair_record)


def test_pair_record_null_description_and_long_text_flag_are_valid(
    pair_record_schema, valid_pair_record
):
    instance = copy.deepcopy(valid_pair_record)
    instance["description_text"] = None
    instance["quality_flags"] = ["long_text"]

    assert_valid(pair_record_schema, instance)


def test_pair_record_missing_artifact_id_fails(
    pair_record_schema, valid_pair_record
):
    instance = copy.deepcopy(valid_pair_record)
    del instance["artifact_id"]

    errors = assert_invalid(pair_record_schema, instance)
    assert any(
        error.validator == "required" and "artifact_id" in error.message
        for error in errors
    )


def test_pair_record_missing_mapping_fails(pair_record_schema, valid_pair_record):
    instance = copy.deepcopy(valid_pair_record)
    del instance["provenance"]["mapping"]

    errors = assert_invalid(pair_record_schema, instance)
    assert any(
        list(error.absolute_path) == ["provenance"]
        and error.validator == "required"
        and "mapping" in error.message
        for error in errors
    )


def test_negative_control_corrupted_pair_record_fails(
    pair_record_schema, valid_pair_record
):
    # Baseline: the untouched instance is green.
    assert_valid(pair_record_schema, valid_pair_record)

    broken = copy.deepcopy(valid_pair_record)
    broken["quality_flags"] = ["not_a_real_flag"]

    errors = assert_invalid(pair_record_schema, broken)
    assert any(
        list(error.absolute_path) == ["quality_flags", 0]
        and error.validator == "enum"
        for error in errors
    )
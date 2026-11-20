"""T-001: ArtifactMap positive cases, required-field and enum rejections."""

import copy

import pytest

from conftest import assert_invalid, assert_valid


def test_valid_artifact_map_passes(artifact_map_schema, valid_artifact_map):
    assert_valid(artifact_map_schema, valid_artifact_map)


def test_artifact_map_missing_required_units_fails(
    artifact_map_schema, valid_artifact_map
):
    instance = copy.deepcopy(valid_artifact_map)
    del instance["units"]

    errors = assert_invalid(artifact_map_schema, instance)
    assert any(
        error.validator == "required" and "units" in error.message for error in errors
    )


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (["line"], "two_line"),
        (["case_type"], "rule_c"),
        (["units", 0, "scale_bindings", 0, "source"], "L4_manual"),
    ],
)
def test_artifact_map_illegal_enums_fail(
    artifact_map_schema, valid_artifact_map, path, bad_value
):
    instance = copy.deepcopy(valid_artifact_map)
    target = instance
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    errors = assert_invalid(artifact_map_schema, instance)
    assert any(
        list(error.absolute_path) == path and error.validator == "enum"
        for error in errors
    )


def test_negative_control_corrupted_artifact_map_fails(
    artifact_map_schema, valid_artifact_map
):
    # Baseline: the untouched instance is green.
    assert_valid(artifact_map_schema, valid_artifact_map)

    broken = copy.deepcopy(valid_artifact_map)
    broken["units"][0]["confidence"] = 1.5

    errors = assert_invalid(artifact_map_schema, broken)
    assert any(
        error.validator == "maximum"
        and list(error.absolute_path) == ["units", 0, "confidence"]
        for error in errors
    )
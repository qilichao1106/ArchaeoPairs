"""T-001: the frozen schemas themselves are loadable and Draft 2020-12 valid."""

import pytest
from jsonschema import Draft202012Validator

from conftest import assert_invalid, assert_valid, load_schema

SCHEMA_NAMES = ["artifact_map.schema.json", "pair_record.schema.json"]
ALARM_CODES = ["E001", "E002", "E003", "E004", "E005", "E006", "E007"]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_loadable_and_draft_2020_12_valid(name):
    schema = load_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    # Raises jsonschema.SchemaError if the schema is not a valid 2020-12 schema.
    Draft202012Validator.check_schema(schema)


def test_artifact_map_alarm_enum_is_exactly_e001_to_e007(
    artifact_map_schema, valid_artifact_map
):
    alarms = artifact_map_schema["properties"]["alarms"]["items"]["enum"]
    assert len(alarms) == 7
    assert sorted(alarms) == ALARM_CODES

    for code in ALARM_CODES:
        instance = dict(valid_artifact_map, alarms=[code])
        assert_valid(artifact_map_schema, instance)

    for code in ("E000", "E008", "e001"):
        instance = dict(valid_artifact_map, alarms=[code])
        errors = assert_invalid(artifact_map_schema, instance)
        assert any(list(error.absolute_path) == ["alarms", 0] for error in errors)
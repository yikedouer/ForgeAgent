"""JSON schema value validator tests."""

from __future__ import annotations

from forgecc.toolkit_schema_value import _schema_value_error


def test_schema_value_error_validates_number_bounds() -> None:
    assert _schema_value_error(3, {"type": "integer", "minimum": 1}, "count") is None
    assert _schema_value_error(0, {"type": "integer", "minimum": 1}, "count") == (
        "argument 'count' must be at least 1"
    )


def test_schema_value_error_validates_nested_object_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }

    assert _schema_value_error({"config": {"path": "README.md"}}, schema, "args") is None
    assert _schema_value_error({"config": {}}, schema, "args") == (
        "missing required argument(s): args.config.path"
    )

from forgeagent.toolkit_schema import arg_type_error


def test_arg_type_error_accepts_valid_object_args() -> None:
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    assert arg_type_error(schema, {"path": "README.md", "limit": 3}) is None


def test_arg_type_error_rejects_missing_required_arg() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    assert arg_type_error(schema, {}) == "missing required argument(s): args.path"


def test_arg_type_error_validates_pattern_properties() -> None:
    schema = {
        "type": "object",
        "properties": {},
        "patternProperties": {
            "^env_[A-Z]+$": {"type": "string"},
        },
        "additionalProperties": False,
    }

    assert arg_type_error(schema, {"env_PATH": "/bin"}) is None
    assert arg_type_error(schema, {"env_PATH": 12}) == "argument 'args.env_PATH' must be string"


def test_arg_type_error_validates_unique_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "required": ["names"],
        "additionalProperties": False,
    }

    assert arg_type_error(schema, {"names": ["alpha", "beta"]}) is None
    assert arg_type_error(schema, {"names": ["alpha", "alpha"]}) == (
        "argument 'args.names' must contain unique items"
    )

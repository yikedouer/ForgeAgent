"""JSON schema validation helpers for tool argument objects."""

from __future__ import annotations

from .toolkit_schema_value import _pattern_property_keys, _schema_value_error


def arg_type_error(parameters: dict, args: dict) -> str | None:
    """Return a human-readable validation error for tool args, if any."""
    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        return None
    root_schema = dict(parameters)
    root_schema["additionalProperties"] = True
    error = _schema_value_error(args, root_schema, "args")
    if error:
        return error
    root_pattern_keys, pattern_error = _pattern_property_keys(
        args,
        parameters.get("patternProperties"),
        "args",
    )
    if pattern_error:
        return pattern_error
    unknown = [key for key in args if key not in properties and key not in root_pattern_keys]
    additional = parameters.get("additionalProperties")
    if isinstance(additional, dict):
        for key in unknown:
            error = _schema_value_error(args[key], additional, key)
            if error:
                return error
    elif additional is not True and unknown:
        names = ", ".join(str(key) for key in unknown)
        return f"unknown argument(s): {names}"
    for key, value in args.items():
        schema = properties.get(key)
        if isinstance(schema, dict):
            error = _schema_value_error(value, schema, key)
            if error:
                return error
    return None

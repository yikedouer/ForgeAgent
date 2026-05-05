"""JSON schema validation helpers for tool argument objects."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def arg_type_error(parameters: dict, args: dict) -> str | None:
    """Return a human-readable validation error for tool args, if any."""
    if not isinstance(parameters, dict):
        return None
    schema = _strict_schema(parameters)
    error = _unique_items_serializable_error(args, schema, "args")
    if error is not None:
        return error
    return _schema_value_error(args, schema, "args")


def _schema_value_error(value: object, schema: dict, label: str) -> str | None:
    """Validate one value against JSON Schema and return ForgeAgent-style text."""
    try:
        validator = Draft202012Validator(schema)
        error = next(validator.iter_errors(value), None)
    except Exception as exc:
        return f"invalid schema for argument '{label}': {exc}"
    if error is None:
        return None
    return _format_error(error, label)


def _format_error(error: ValidationError, root_label: str) -> str:
    location = _label(root_label, error.absolute_path)
    if "propertyNames" in error.absolute_schema_path and isinstance(error.instance, str):
        location = f"{location}.{error.instance}"
    branch = _conditional_branch(error)
    combinator = _combinator(error)
    message = _format_error_message(error, location)
    if branch:
        return f"argument '{location}' must match {branch} schema: {message}"
    if combinator:
        return f"argument '{location}' must match {combinator} schema: {message}"
    return message


def _label(root: str, path: Iterable[object]) -> str:
    text = root
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}"
    return text


def _conditional_branch(error: ValidationError) -> str:
    for part in error.absolute_schema_path:
        if part in {"then", "else"}:
            return str(part)
    return ""


def _combinator(error: ValidationError) -> str:
    for part in error.absolute_schema_path:
        if part in {"allOf", "anyOf", "oneOf"}:
            return str(part)
    return ""


def _format_error_message(error: ValidationError, label: str) -> str:
    validator = error.validator
    validator_value = error.validator_value
    if validator == "required":
        missing = _missing_required_name(error)
        if missing:
            return f"missing required argument(s): {label}.{missing}"
    if validator == "additionalProperties":
        unknown = _unknown_property_names(error)
        if unknown:
            names = ", ".join(f"{label}.{name}" for name in unknown)
            return f"unknown argument(s): {names}"
    if validator == "propertyNames":
        key_label = f"{label}.{error.instance}" if isinstance(error.instance, str) else label
        nested = next(iter(error.context), None)
        if nested is not None:
            return _format_error_message(nested, key_label)
        return f"argument '{key_label}' {error.message}"
    if validator == "anyOf":
        return f"argument '{label}' must match at least one anyOf schema"
    if validator == "oneOf":
        return f"argument '{label}' must match exactly one oneOf schema"
    if validator == "type":
        return f"argument '{label}' must be {_type_name(validator_value)}"
    if validator == "minLength":
        return f"argument '{label}' must be at least {validator_value} characters"
    if validator == "maxLength":
        return f"argument '{label}' must be at most {validator_value} characters"
    if validator == "pattern":
        return f"argument '{label}' must match pattern: {validator_value}"
    if validator == "minimum":
        return f"argument '{label}' must be at least {validator_value}"
    if validator == "exclusiveMinimum":
        return f"argument '{label}' must be greater than {validator_value}"
    if validator == "maximum":
        return f"argument '{label}' must be at most {validator_value}"
    if validator == "exclusiveMaximum":
        return f"argument '{label}' must be less than {validator_value}"
    if validator == "multipleOf":
        return f"argument '{label}' must be a multiple of {validator_value}"
    if validator == "enum":
        allowed = ", ".join(str(choice) for choice in validator_value)
        return f"argument '{label}' must be one of: {allowed}"
    if validator == "const":
        return f"argument '{label}' must be {validator_value}"
    if validator == "minProperties":
        return f"argument '{label}' must contain at least {validator_value} properties"
    if validator == "maxProperties":
        return f"argument '{label}' must contain at most {validator_value} properties"
    if validator == "minItems":
        return f"argument '{label}' must contain at least {validator_value} items"
    if validator == "maxItems":
        return f"argument '{label}' must contain at most {validator_value} items"
    if validator == "uniqueItems":
        return f"argument '{label}' must contain unique items"
    if validator == "contains":
        return f"argument '{label}' must contain at least 1 matching item(s)"
    if validator == "minContains":
        return f"argument '{label}' must contain at least {validator_value} matching item(s)"
    if validator == "maxContains":
        return f"argument '{label}' must contain at most {validator_value} matching item(s)"
    if validator == "items" and validator_value is False:
        extra_index = len(error.schema.get("prefixItems", []))
        return f"argument '{label}[{extra_index}]' contains additional item(s)"
    if validator == "prefixItems":
        return f"argument '{label}' contains additional item(s)"
    return f"argument '{label}' {error.message}"


def _missing_required_name(error: ValidationError) -> str:
    message = error.message
    if message.startswith("'") and "' is a required property" in message:
        return message.split("'", 2)[1]
    return ""


def _unknown_property_names(error: ValidationError) -> list[str]:
    unknown = getattr(error, "params", {}).get("additionalProperties")
    if isinstance(unknown, set):
        return sorted(str(name) for name in unknown)
    message = error.message
    if "(" not in message or " unexpected" not in message:
        if " does not match any of the regexes" in message:
            return [message.split("'", 2)[1]]
        return []
    raw = message.split("(", 1)[1].split(" unexpected", 1)[0]
    return [part.strip(" '") for part in raw.split(",") if part.strip(" '")]


def _type_name(value: Any) -> str:
    if isinstance(value, list):
        return "one of: " + ", ".join(str(item) for item in value)
    return str(value)


def _strict_schema(schema: object, *, conditional: bool = False) -> object:
    """Match ForgeAgent's historical default: object schemas reject unknown keys."""
    if isinstance(schema, list):
        return [_strict_schema(item, conditional=conditional) for item in schema]
    if not isinstance(schema, dict):
        return schema

    copy: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "dependentSchemas" and isinstance(value, dict):
            copy[key] = {
                name: _strict_schema(child, conditional=True)
                for name, child in value.items()
            }
        else:
            copy[key] = _strict_schema(value, conditional=key in {"if", "then", "else"})

    objectish = (
        copy.get("type") == "object"
        or "properties" in copy
        or "patternProperties" in copy
        or schema == {}
    )
    if objectish and "additionalProperties" not in copy:
        copy["additionalProperties"] = True if conditional else False
    if schema == {}:
        copy.setdefault("type", "object")
        copy.setdefault("properties", {})
    return copy


def _unique_items_serializable_error(
    value: object,
    schema: object,
    label: str,
) -> str | None:
    if not isinstance(schema, dict):
        return None
    if schema.get("uniqueItems") is True and isinstance(value, list):
        for item in value:
            try:
                json.dumps(item, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                return f"argument '{label}' must contain JSON-serializable items"
    expected = schema.get("type")
    if isinstance(value, dict) and (expected == "object" or "properties" in schema):
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, item in value.items():
                child_schema = properties.get(key)
                error = _unique_items_serializable_error(item, child_schema, f"{label}.{key}")
                if error:
                    return error
    if isinstance(value, list):
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, list):
            for idx, child_schema in enumerate(prefix_items[:len(value)]):
                error = _unique_items_serializable_error(value[idx], child_schema, f"{label}[{idx}]")
                if error:
                    return error
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                error = _unique_items_serializable_error(item, item_schema, f"{label}[{idx}]")
                if error:
                    return error
    return None

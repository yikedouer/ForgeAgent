"""Recursive JSON schema value validation."""

from __future__ import annotations

import json
import re


JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "array": list,
    "object": dict,
    "boolean": bool,
}


def _matches_json_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected not in JSON_TYPES:
        return True
    expected_type = JSON_TYPES[expected]
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, expected_type) and not isinstance(value, bool)
    return isinstance(value, expected_type)


def _pattern_property_keys(
    value: dict,
    pattern_properties: object,
    label: str,
) -> tuple[set[str], str | None]:
    keys: set[str] = set()
    if not isinstance(pattern_properties, dict):
        return keys, None
    for pattern, child_schema in pattern_properties.items():
        if not isinstance(pattern, str) or not isinstance(child_schema, dict):
            continue
        try:
            keys.update(key for key in value if re.search(pattern, key))
        except re.error as exc:
            return keys, f"invalid patternProperties pattern for argument '{label}': {exc}"
    return keys, None


def _schema_value_error(value: object, schema: dict, label: str) -> str | None:
    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all(isinstance(child, dict) for child in all_of):
        for child in all_of:
            error = _schema_value_error(value, child, label)
            if error:
                return f"argument '{label}' must match all allOf schemas: {error}"

    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and all(isinstance(child, dict) for child in any_of):
        if not any(_schema_value_error(value, child, label) is None for child in any_of):
            return f"argument '{label}' must match at least one anyOf schema"

    one_of = schema.get("oneOf")
    if isinstance(one_of, list) and all(isinstance(child, dict) for child in one_of):
        matches = sum(1 for child in one_of if _schema_value_error(value, child, label) is None)
        if matches != 1:
            return f"argument '{label}' must match exactly one oneOf schema"

    not_schema = schema.get("not")
    if isinstance(not_schema, dict) and _schema_value_error(value, not_schema, label) is None:
        return f"argument '{label}' must not match not schema"

    if_schema = schema.get("if")
    if isinstance(if_schema, dict):
        checked_if_schema = dict(if_schema)
        checked_if_schema.setdefault("additionalProperties", True)
        branch_name = "then" if _schema_value_error(value, checked_if_schema, label) is None else "else"
        branch_schema = schema.get(branch_name)
        if isinstance(branch_schema, dict):
            checked_schema = dict(branch_schema)
            checked_schema.setdefault("additionalProperties", True)
            error = _schema_value_error(value, checked_schema, label)
            if error:
                return f"argument '{label}' must match {branch_name} schema: {error}"

    expected = schema.get("type")
    if isinstance(expected, list) and all(isinstance(t, str) for t in expected):
        if not any(_matches_json_type(value, t) for t in expected):
            allowed = ", ".join(expected)
            return f"argument '{label}' must be one of: {allowed}"
    elif isinstance(expected, str) and expected in {*JSON_TYPES, "null"}:
        if not _matches_json_type(value, expected):
            return f"argument '{label}' must be {expected}"

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return f"argument '{label}' must be at least {min_length} characters"
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            return f"argument '{label}' must be at most {max_length} characters"
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    return f"argument '{label}' must match pattern: {pattern}"
            except re.error as exc:
                return f"invalid pattern for argument '{label}': {exc}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"argument '{label}' must be at least {minimum}"
        exclusive_minimum = schema.get("exclusiveMinimum")
        if (
            isinstance(exclusive_minimum, (int, float))
            and not isinstance(exclusive_minimum, bool)
            and value <= exclusive_minimum
        ):
            return f"argument '{label}' must be greater than {exclusive_minimum}"
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            return f"argument '{label}' must be at most {maximum}"
        exclusive_maximum = schema.get("exclusiveMaximum")
        if (
            isinstance(exclusive_maximum, (int, float))
            and not isinstance(exclusive_maximum, bool)
            and value >= exclusive_maximum
        ):
            return f"argument '{label}' must be less than {exclusive_maximum}"
        multiple_of = schema.get("multipleOf")
        if (
            isinstance(multiple_of, (int, float))
            and not isinstance(multiple_of, bool)
            and multiple_of > 0
            and value % multiple_of != 0
        ):
            return f"argument '{label}' must be a multiple of {multiple_of}"

    if "const" in schema and value != schema["const"]:
        return f"argument '{label}' must be {schema['const']}"
    choices = schema.get("enum")
    if isinstance(choices, list) and value not in choices:
        allowed = ", ".join(str(choice) for choice in choices)
        return f"argument '{label}' must be one of: {allowed}"

    object_keywords = {
        "additionalProperties",
        "dependentRequired",
        "dependentSchemas",
        "maxProperties",
        "minProperties",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
    }
    if isinstance(value, dict) and (expected == "object" or bool(object_keywords & schema.keys())):
        min_properties = schema.get("minProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            return f"argument '{label}' must contain at least {min_properties} properties"
        max_properties = schema.get("maxProperties")
        if isinstance(max_properties, int) and len(value) > max_properties:
            return f"argument '{label}' must contain at most {max_properties} properties"
        property_names = schema.get("propertyNames")
        if isinstance(property_names, dict):
            for key in value:
                error = _schema_value_error(key, property_names, f"{label}.{key}")
                if error:
                    return error
        pattern_properties = schema.get("patternProperties")
        pattern_property_keys, pattern_error = _pattern_property_keys(value, pattern_properties, label)
        if pattern_error:
            return pattern_error
        if isinstance(pattern_properties, dict):
            for pattern, child_schema in pattern_properties.items():
                if not isinstance(pattern, str) or not isinstance(child_schema, dict):
                    continue
                for key in pattern_property_keys:
                    if re.search(pattern, key) is None:
                        continue
                    error = _schema_value_error(value[key], child_schema, f"{label}.{key}")
                    if error:
                        return error
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    return f"missing required argument(s): {label}.{key}"
        dependent_required = schema.get("dependentRequired")
        if isinstance(dependent_required, dict):
            for key, dependencies in dependent_required.items():
                if not isinstance(key, str) or key not in value or not isinstance(dependencies, list):
                    continue
                missing = [dep for dep in dependencies if isinstance(dep, str) and dep not in value]
                if missing:
                    names = ", ".join(f"{label}.{dep}" for dep in missing)
                    return f"argument '{label}.{key}' requires: {names}"
        dependent_schemas = schema.get("dependentSchemas")
        if isinstance(dependent_schemas, dict):
            for key, dependent_schema in dependent_schemas.items():
                if not isinstance(key, str) or key not in value or not isinstance(dependent_schema, dict):
                    continue
                checked_schema = dict(dependent_schema)
                checked_schema.setdefault("additionalProperties", True)
                error = _schema_value_error(value, checked_schema, label)
                if error:
                    return f"argument '{label}.{key}' requires dependent schema: {error}"
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            additional = schema.get("additionalProperties")
            unknown = [key for key in value if key not in properties and key not in pattern_property_keys]
            if isinstance(additional, dict):
                for key in unknown:
                    error = _schema_value_error(value[key], additional, f"{label}.{key}")
                    if error:
                        return error
            elif additional is not True and unknown:
                names = ", ".join(f"{label}.{key}" for key in unknown)
                return f"unknown argument(s): {names}"
            for key, child in value.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, dict):
                    error = _schema_value_error(child, child_schema, f"{label}.{key}")
                    if error:
                        return error

    if expected == "array" and isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            return f"argument '{label}' must contain at least {min_items} items"
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            return f"argument '{label}' must contain at most {max_items} items"
        if schema.get("uniqueItems") is True:
            seen: set[str] = set()
            for item in value:
                try:
                    marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
                except (TypeError, ValueError):
                    return f"argument '{label}' must contain JSON-serializable items"
                if marker in seen:
                    return f"argument '{label}' must contain unique items"
                seen.add(marker)
        contains = schema.get("contains")
        if isinstance(contains, dict):
            matches = sum(
                1
                for idx, item in enumerate(value)
                if _schema_value_error(item, contains, f"{label}[{idx}]") is None
            )
            min_contains = schema.get("minContains", 1)
            if isinstance(min_contains, int) and matches < min_contains:
                return f"argument '{label}' must contain at least {min_contains} matching item(s)"
            max_contains = schema.get("maxContains")
            if isinstance(max_contains, int) and matches > max_contains:
                return f"argument '{label}' must contain at most {max_contains} matching item(s)"
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, list):
            for idx, child_schema in enumerate(prefix_items):
                if idx >= len(value):
                    break
                if isinstance(child_schema, dict):
                    error = _schema_value_error(value[idx], child_schema, f"{label}[{idx}]")
                    if error:
                        return error
            if schema.get("items") is False and len(value) > len(prefix_items):
                return f"argument '{label}[{len(prefix_items)}]' contains additional item(s)"
        elif schema.get("items") is False and value:
            return f"argument '{label}[0]' contains additional item(s)"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                error = _schema_value_error(item, item_schema, f"{label}[{idx}]")
                if error:
                    return error
    return None

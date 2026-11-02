"""Output validation -- every node output is checked before routing."""
from __future__ import annotations

class ValidationError(Exception):
    pass

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}

def _check(value, schema, path, errors):
    types = schema.get("type")
    if types:
        if isinstance(types, str):
            types = [types]
        if not any(_TYPE_CHECKS[t](value) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(value).__name__}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required field '{req}'")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value:
                _check(value[key], subschema, f"{path}.{key}", errors)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)

def validate(instance, schema) -> list[str]:
    errors: list[str] = []
    _check(instance, schema, "$", errors)
    return errors

def validate_or_raise(node_id: str, output: dict, schema: dict) -> dict:
    errors = validate(output, schema)
    if errors:
        raise ValidationError(f"{node_id} output failed schema validation: {errors}")
    return output
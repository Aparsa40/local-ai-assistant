"""Explicit tool registration and restricted JSON-schema validation."""
from __future__ import annotations

import copy
import json
from typing import Any, Callable

from core.permissions.types import AccessRequest
from .schemas import ToolCallRequest, ToolDefinition


class ToolRegistryError(Exception):
    """Base class for tool registry failures."""


class ToolNotFoundError(ToolRegistryError):
    """The requested tool ID/version is not registered."""


class ToolDisabledError(ToolRegistryError):
    """The registered tool is disabled."""


class ToolInputValidationError(ToolRegistryError, ValueError):
    """Tool input does not satisfy its registered schema or size limits."""


class ToolSchemaDefinitionError(ToolRegistryError, ValueError):
    """A tool registered an unsupported or malformed schema."""


_ALLOWED_TYPES = {"object", "string", "integer", "number", "boolean", "array", "null"}
_SCHEMA_KEYS = {
    "type", "properties", "required", "additionalProperties", "enum",
    "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "items",
}


def _validate_schema_definition(schema: dict[str, Any], *, depth: int = 0) -> None:
    if depth > 8:
        raise ToolSchemaDefinitionError("Tool schema nesting exceeds the supported depth.")
    if not isinstance(schema, dict) or set(schema) - _SCHEMA_KEYS:
        raise ToolSchemaDefinitionError("Tool schema contains unsupported keywords.")
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _ALLOWED_TYPES:
        raise ToolSchemaDefinitionError("Tool schema must declare a supported type.")
    type_keys = {
        "object": {"type", "properties", "required", "additionalProperties", "enum"},
        "array": {"type", "items", "minItems", "maxItems", "enum"},
        "string": {"type", "minLength", "maxLength", "enum"},
        "integer": {"type", "minimum", "maximum", "enum"},
        "number": {"type", "minimum", "maximum", "enum"},
        "boolean": {"type", "enum"},
        "null": {"type", "enum"},
    }
    if set(schema) - type_keys[schema_type]:
        raise ToolSchemaDefinitionError("Tool schema contains keywords invalid for its declared type.")
    if "enum" in schema and (
        not isinstance(schema["enum"], list)
        or not schema["enum"]
        or len(schema["enum"]) > 100
    ):
        raise ToolSchemaDefinitionError("Tool schema enum must contain 1..100 values.")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or len(properties) > 100:
            raise ToolSchemaDefinitionError("Object properties must be a bounded object.")
        if not isinstance(required, list) or len(required) > 100 or any(not isinstance(item, str) for item in required):
            raise ToolSchemaDefinitionError("Required fields must be a bounded string list.")
        if len(set(required)) != len(required) or not set(required).issubset(properties):
            raise ToolSchemaDefinitionError("Required fields must be unique declared properties.")
        if not isinstance(schema.get("additionalProperties", False), bool):
            raise ToolSchemaDefinitionError("additionalProperties must be a boolean.")
        for name, child in properties.items():
            if not isinstance(name, str) or not name or len(name) > 100:
                raise ToolSchemaDefinitionError("Property names must be non-empty strings.")
            _validate_schema_definition(child, depth=depth + 1)
    elif schema_type == "array":
        if "items" not in schema:
            raise ToolSchemaDefinitionError("Array schemas must declare items.")
        _validate_schema_definition(schema["items"], depth=depth + 1)

    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (
            isinstance(schema[key], bool) or not isinstance(schema[key], int) or schema[key] < 0
        ):
            raise ToolSchemaDefinitionError(f"{key} must be a non-negative integer.")
    for key in ("minimum", "maximum"):
        if key in schema and (
            isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))
        ):
            raise ToolSchemaDefinitionError(f"{key} must be numeric.")
    if schema.get("minimum") is not None and schema.get("maximum") is not None:
        if schema["minimum"] > schema["maximum"]:
            raise ToolSchemaDefinitionError("minimum cannot exceed maximum.")
    if schema.get("minLength", 0) > schema.get("maxLength", float("inf")):
        raise ToolSchemaDefinitionError("minLength cannot exceed maxLength.")
    if schema.get("minItems", 0) > schema.get("maxItems", float("inf")):
        raise ToolSchemaDefinitionError("minItems cannot exceed maxItems.")


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    return value is None


def _validate_value(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    schema_type = schema["type"]
    if not _matches_type(value, schema_type):
        raise ToolInputValidationError(f"{path} must be {schema_type}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolInputValidationError(f"{path} is not an allowed value.")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise ToolInputValidationError(f"{path} is missing required fields.")
        if not schema.get("additionalProperties", False) and set(value) - set(properties):
            raise ToolInputValidationError(f"{path} contains unsupported fields.")
        for name, item in value.items():
            if name in properties:
                _validate_value(item, properties[name], path=f"{path}.{name}")
    elif schema_type == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise ToolInputValidationError(f"{path} length is outside the allowed range.")
    elif schema_type in {"integer", "number"}:
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ToolInputValidationError(f"{path} is outside the allowed numeric range.")
    elif schema_type == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ToolInputValidationError(f"{path} item count is outside the allowed range.")
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], path=f"{path}[{index}]")


class ToolRegistry:
    """Stores only explicitly registered, versioned tool definitions and handlers."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], ToolDefinition] = {}
        self._handlers: dict[tuple[str, str], Callable[..., Any]] = {}

    def register(self, definition: ToolDefinition, handler: Callable[..., Any]) -> None:
        if not isinstance(definition, ToolDefinition):
            raise TypeError("definition must be a ToolDefinition")
        if not callable(handler):
            raise TypeError("handler must be callable")
        _validate_schema_definition(definition.input_schema)
        if definition.output_schema is not None:
            _validate_schema_definition(definition.output_schema)
        key = (definition.tool_id, definition.version)
        if key in self._definitions:
            raise ToolRegistryError("A tool with this ID and version is already registered.")
        definition = copy.deepcopy(definition)
        self._definitions[key] = definition
        self._handlers[key] = handler

    def get_definition(self, tool_id: str, version: str) -> ToolDefinition:
        key = (tool_id, version)
        definition = self._definitions.get(key)
        if definition is None:
            raise ToolNotFoundError("The requested tool is not registered.")
        if not definition.enabled:
            raise ToolDisabledError("The requested tool is disabled.")
        return copy.deepcopy(definition)

    def validate_call(self, request: ToolCallRequest) -> tuple[ToolDefinition, dict[str, Any]]:
        if not isinstance(request, ToolCallRequest):
            raise TypeError("request must be a ToolCallRequest")
        definition = self.get_definition(request.tool_id, request.version)
        access_request: AccessRequest = request.access_request
        if access_request.resource.resource_type is not definition.resource_type:
            raise ToolInputValidationError("Tool resource type does not match its registered contract.")
        if access_request.operation is not definition.operation:
            raise ToolInputValidationError("Tool operation does not match its registered contract.")
        try:
            encoded = json.dumps(
                request.input_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolInputValidationError("Tool input must be JSON-compatible.") from exc
        if len(encoded) > definition.max_input_bytes:
            raise ToolInputValidationError("Tool input exceeds the registered size limit.")
        _validate_value(request.input_data, definition.input_schema)
        return definition, copy.deepcopy(request.input_data)

    def _resolve_handler(self, tool_id: str, version: str) -> Callable[..., Any]:
        """Internal runtime-only lookup; never serialize or expose handlers to models."""
        self.get_definition(tool_id, version)
        return self._handlers[(tool_id, version)]

    def public_catalog(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "tool_id": item.tool_id,
                "version": item.version,
                "description": item.description,
                "resource_type": item.resource_type.value,
                "operation": item.operation.value,
                "risk_class": item.risk_class.value,
                "requires_approval": item.requires_approval,
            }
            for item in sorted(self._definitions.values(), key=lambda value: (value.tool_id, value.version))
            if item.enabled
        )

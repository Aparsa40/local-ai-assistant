import pytest

from core.permissions.types import (
    AccessRequest,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.tools.registry import (
    ToolDisabledError,
    ToolInputValidationError,
    ToolNotFoundError,
    ToolRegistry,
    ToolRegistryError,
    ToolSchemaDefinitionError,
)
from core.tools.schemas import ToolCallRequest, ToolDefinition, ToolRiskClass


async def _echo(value):
    return value


def _definition(**overrides) -> ToolDefinition:
    values = {
        "tool_id": "conversation.read",
        "version": "1.0.0",
        "description": "Read a bounded conversation resource.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "include_metadata": {"type": "boolean"},
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        "resource_type": ResourceType.CONVERSATION,
        "operation": PermissionOperation.READ,
        "risk_class": ToolRiskClass.READ_ONLY,
        "max_input_bytes": 1024,
    }
    values.update(overrides)
    return ToolDefinition(**values)


def _call(definition: ToolDefinition, input_data=None, **overrides) -> ToolCallRequest:
    request = AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "tool-gateway"),
        resource=PermissionResource(definition.resource_type, "conversation-1"),
        operation=definition.operation,
        scope=PermissionScope(ScopeType.CONVERSATION, "conversation-1", "owner-1"),
        request_id="tool-request-1",
    )
    values = {
        "tool_id": definition.tool_id,
        "version": definition.version,
        "access_request": request,
        "input_data": {"limit": 10} if input_data is None else input_data,
    }
    values.update(overrides)
    return ToolCallRequest(**values)


def test_registry_registers_and_validates_a_bounded_tool() -> None:
    registry = ToolRegistry()
    registry.register(_definition(), _echo)

    definition, normalized = registry.validate_call(_call(_definition()))

    assert definition.tool_id == "conversation.read"
    assert normalized == {"limit": 10}


def test_registry_rejects_unknown_or_disabled_tools() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get_definition("unknown.tool", "1.0.0")

    disabled = _definition(enabled=False)
    registry.register(disabled, _echo)
    with pytest.raises(ToolDisabledError):
        registry.validate_call(_call(disabled))


def test_registry_rejects_duplicate_id_and_version() -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register(definition, _echo)

    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(definition, _echo)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"limit": 0},
        {"limit": 21},
        {"limit": "10"},
        {"limit": 10, "unexpected": True},
        {"limit": 10, "include_metadata": "yes"},
    ],
)
def test_registry_rejects_invalid_inputs(payload) -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register(definition, _echo)

    with pytest.raises(ToolInputValidationError):
        registry.validate_call(_call(definition, payload))


def test_registry_rejects_non_json_and_oversized_inputs() -> None:
    registry = ToolRegistry()
    definition = _definition(max_input_bytes=20)
    registry.register(definition, _echo)

    with pytest.raises(ToolInputValidationError):
        registry.validate_call(_call(definition, {"limit": 10, "include_metadata": True}))

    larger = _definition(max_input_bytes=1024)
    registry2 = ToolRegistry()
    registry2.register(larger, _echo)
    with pytest.raises(ToolInputValidationError):
        registry2.validate_call(_call(larger, {"limit": object()}))


def test_registry_rejects_resource_and_operation_mismatch() -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register(definition, _echo)
    bad_request = AccessRequest(
        subject=PermissionSubject(SubjectType.SERVICE, "tool-gateway"),
        resource=PermissionResource(ResourceType.FILE, "file-1"),
        operation=PermissionOperation.READ,
        scope=PermissionScope(ScopeType.LOCAL, "machine", "owner-1"),
        request_id="tool-request-2",
    )

    with pytest.raises(ToolInputValidationError, match="resource type"):
        registry.validate_call(
            ToolCallRequest(definition.tool_id, definition.version, bad_request, {"limit": 1})
        )


def test_registry_rejects_unsupported_schema_keywords() -> None:
    registry = ToolRegistry()
    definition = _definition(input_schema={"type": "object", "$ref": "https://example.invalid/schema"})

    with pytest.raises(ToolSchemaDefinitionError):
        registry.register(definition, _echo)


def test_destructive_and_external_tools_must_require_approval() -> None:
    with pytest.raises(ValueError, match="require explicit approval"):
        _definition(
            tool_id="conversation.delete",
            operation=PermissionOperation.DELETE,
            risk_class=ToolRiskClass.DESTRUCTIVE,
            requires_approval=False,
        )

    with pytest.raises(ValueError, match="require explicit approval"):
        _definition(
            tool_id="knowledge.publish",
            operation=PermissionOperation.PUBLISH,
            risk_class=ToolRiskClass.EXTERNAL_SIDE_EFFECT,
            requires_approval=False,
        )


def test_public_catalog_does_not_expose_handlers_or_raw_schemas() -> None:
    registry = ToolRegistry()
    registry.register(_definition(), _echo)

    catalog = registry.public_catalog()

    assert catalog == ({
        "tool_id": "conversation.read",
        "version": "1.0.0",
        "description": "Read a bounded conversation resource.",
        "resource_type": "conversation",
        "operation": "read",
        "risk_class": "read_only",
        "requires_approval": False,
    },)
    assert "handler" not in catalog[0]
    assert "input_schema" not in catalog[0]



def test_registry_rejects_synchronous_handlers() -> None:
    registry = ToolRegistry()
    definition = _definition()

    with pytest.raises(TypeError, match="async callables"):
        registry.register(definition, lambda value: value)


def test_registry_rejects_type_incompatible_schema_keywords() -> None:
    registry = ToolRegistry()
    definition = _definition(
        input_schema={
            "type": "string",
            "properties": {"unexpected": {"type": "string"}},
        }
    )

    with pytest.raises(ToolSchemaDefinitionError):
        registry.register(definition, _echo)

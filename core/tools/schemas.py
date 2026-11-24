"""Typed, bounded tool contracts; definitions are not permission grants."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.permissions.types import AccessRequest, PermissionOperation, ResourceType


class ToolRiskClass(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_id: str
    version: str
    input_schema: dict[str, Any]
    resource_type: ResourceType
    operation: PermissionOperation
    risk_class: ToolRiskClass
    description: str = ""
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int = 15
    max_input_bytes: int = 16 * 1024
    max_output_bytes: int = 32 * 1024
    requires_approval: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", self.tool_id):
            raise ValueError("tool_id must be a stable lowercase identifier")
        if not isinstance(self.version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValueError("tool version must use semantic version format")
        if not isinstance(self.resource_type, ResourceType):
            raise ValueError("resource_type must be a ResourceType")
        if not isinstance(self.operation, PermissionOperation):
            raise ValueError("operation must be a PermissionOperation")
        if not isinstance(self.risk_class, ToolRiskClass):
            raise ValueError("risk_class must be a ToolRiskClass")
        if not isinstance(self.description, str) or len(self.description) > 500:
            raise ValueError("description must be at most 500 characters")
        for name, value, maximum in (
            ("timeout_seconds", self.timeout_seconds, 120),
            ("max_input_bytes", self.max_input_bytes, 65536),
            ("max_output_bytes", self.max_output_bytes, 65536),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        if not isinstance(self.requires_approval, bool) or not isinstance(self.enabled, bool):
            raise ValueError("requires_approval and enabled must be booleans")
        if self.risk_class in {ToolRiskClass.DESTRUCTIVE, ToolRiskClass.EXTERNAL_SIDE_EFFECT} and not self.requires_approval:
            raise ValueError("destructive and external side-effect tools require explicit approval")
        if self.risk_class is ToolRiskClass.READ_ONLY and self.operation is not PermissionOperation.READ:
            raise ValueError("read_only tools must declare the read operation")
        if self.risk_class is ToolRiskClass.DESTRUCTIVE and self.operation is not PermissionOperation.DELETE:
            raise ValueError("destructive tools must declare the delete operation")
        if self.risk_class is ToolRiskClass.EXTERNAL_SIDE_EFFECT and self.operation not in {
            PermissionOperation.PUBLISH,
            PermissionOperation.TRANSMIT,
        }:
            raise ValueError("external side-effect tools must declare publish or transmit")
        if self.risk_class is ToolRiskClass.MUTATING and self.operation not in {
            PermissionOperation.CREATE,
            PermissionOperation.UPDATE,
        }:
            raise ValueError("mutating tools must declare create or update")
        if not isinstance(self.input_schema, dict):
            raise ValueError("input_schema must be a JSON schema object")
        try:
            encoded = json.dumps(self.input_schema, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 16384:
                raise ValueError("input_schema exceeds the size limit")
            if self.output_schema is not None:
                json.dumps(self.output_schema, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("tool schemas must be JSON-compatible") from exc
        object.__setattr__(self, "input_schema", copy.deepcopy(self.input_schema))
        if self.output_schema is not None:
            if not isinstance(self.output_schema, dict):
                raise ValueError("output_schema must be a JSON schema object")
            object.__setattr__(self, "output_schema", copy.deepcopy(self.output_schema))


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    tool_id: str
    version: str
    access_request: AccessRequest
    input_data: dict[str, Any]
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", self.tool_id):
            raise ValueError("tool_id is invalid")
        if not isinstance(self.version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValueError("tool version is invalid")
        if not isinstance(self.access_request, AccessRequest):
            raise ValueError("access_request must be an AccessRequest")
        if not isinstance(self.input_data, dict):
            raise ValueError("input_data must be a JSON object")
        if self.approval_id is not None and (
            not isinstance(self.approval_id, str) or not self.approval_id.strip() or len(self.approval_id) > 80
        ):
            raise ValueError("approval_id is invalid")
        object.__setattr__(self, "input_data", copy.deepcopy(self.input_data))



@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    ok: bool
    tool_id: str
    version: str
    request_id: str
    output: Any = None
    error_category: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    side_effect_may_have_occurred: bool = False

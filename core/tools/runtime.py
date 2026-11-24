"""Only execution gateway for explicitly registered, permissioned tools."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from core.permissions.approvals import ApprovalService
from core.permissions.audit import AuditService
from core.permissions.manager import PermissionManager
from core.permissions.types import DecisionEffect
from .registry import ToolInputValidationError, ToolRegistry, ToolRegistryError
from .schemas import ToolCallRequest, ToolDefinition, ToolExecutionResult, ToolRiskClass


class ToolRuntime:
    """Validates, authorizes, approves, executes, and audits one bounded tool call."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_manager: PermissionManager,
        audit_service: AuditService,
        *,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self.registry = registry
        self.permission_manager = permission_manager
        self.audit_service = audit_service
        self.approval_service = approval_service

    @staticmethod
    def _action_payload(
        request: ToolCallRequest,
        definition: ToolDefinition,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        access = request.access_request
        return {
            "tool_id": definition.tool_id,
            "tool_version": definition.version,
            "resource": {
                "type": access.resource.resource_type.value,
                "id": access.resource.resource_id,
            },
            "operation": access.operation.value,
            "scope": {
                "type": access.scope.scope_type.value,
                "id": access.scope.scope_id,
                "owner_id": access.scope.owner_id,
            },
            "input": input_data,
        }

    def request_approval(
        self,
        request: ToolCallRequest,
        *,
        requested_by: str,
        ttl_seconds: int = 300,
    ):
        """Create a one-time approval for the exact registered action."""
        if self.approval_service is None:
            raise RuntimeError("Approval service is unavailable.")
        definition, input_data = self.registry.validate_call(request)
        decision = self.permission_manager.authorize(request.access_request)
        self.audit_service.record(
            event_type="permission_decision",
            request_id=request.access_request.request_id,
            outcome=decision.effect.value,
            subject=request.access_request.subject,
            resource=request.access_request.resource,
            operation=request.access_request.operation,
            metadata={
                "tool_id": definition.tool_id,
                "reason_code": decision.reason_code,
                "grant_id": decision.grant_id or "",
                "decision": decision.effect.value,
            },
        )
        if decision.effect is DecisionEffect.DENY:
            raise PermissionError("The tool action is not authorized.")
        if not (definition.requires_approval or decision.effect is DecisionEffect.REQUIRE_APPROVAL):
            raise ValueError("This tool action does not require human approval.")
        approval = self.approval_service.request(
            request.access_request,
            self._action_payload(request, definition, input_data),
            requested_by=requested_by,
            ttl_seconds=ttl_seconds,
        )
        return approval

    async def execute(self, request: ToolCallRequest) -> ToolExecutionResult:
        """Execute one call; expected denials/failures return normalized results."""
        if not isinstance(request, ToolCallRequest):
            raise TypeError("request must be a ToolCallRequest")

        access = request.access_request
        request_id = access.request_id
        try:
            definition, input_data = self.registry.validate_call(request)
        except ToolRegistryError as exc:
            self.audit_service.record(
                event_type="tool_request_rejected",
                request_id=request_id,
                outcome="rejected",
                subject=access.subject,
                resource=access.resource,
                operation=access.operation,
                metadata={
                    "tool_id": request.tool_id,
                    "tool_version": request.version,
                    "exception_type": type(exc).__name__,
                },
            )
            return ToolExecutionResult(
                False, request.tool_id, request.version, request_id,
                error_category="tool_validation_failed",
                error_message=str(exc),
            )

        input_bytes = len(json.dumps(
            input_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"))
        self.audit_service.record(
            event_type="tool_request",
            request_id=request_id,
            outcome="received",
            subject=access.subject,
            resource=access.resource,
            operation=access.operation,
            metadata={
                "tool_id": definition.tool_id,
                "tool_version": definition.version,
                "risk_class": definition.risk_class.value,
                "input_bytes": input_bytes,
            },
        )

        decision = self.permission_manager.authorize(access)
        self.audit_service.record(
            event_type="permission_decision",
            request_id=request_id,
            outcome=decision.effect.value,
            subject=access.subject,
            resource=access.resource,
            operation=access.operation,
            metadata={
                "tool_id": definition.tool_id,
                "reason_code": decision.reason_code,
                "grant_id": decision.grant_id or "",
                "decision": decision.effect.value,
            },
        )
        if decision.effect is DecisionEffect.DENY:
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="permission_denied",
                error_message=decision.reason_code,
            )

        needs_approval = (
            definition.requires_approval
            or decision.effect is DecisionEffect.REQUIRE_APPROVAL
        )
        approval_consumed = False
        if needs_approval:
            if self.approval_service is None or not request.approval_id:
                self.audit_service.record(
                    event_type="approval_required",
                    request_id=request_id,
                    outcome="pending",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={"tool_id": definition.tool_id, "reason_code": "approval_required"},
                )
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="approval_required",
                    error_message="This action requires a valid one-time approval.",
                )
            consumed = self.approval_service.consume(
                request.approval_id,
                access,
                self._action_payload(request, definition, input_data),
            )
            if consumed is None:
                self.audit_service.record(
                    event_type="approval_rejected",
                    request_id=request_id,
                    outcome="denied",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={
                        "tool_id": definition.tool_id,
                        "approval_id": request.approval_id,
                        "reason_code": "approval_invalid_expired_or_consumed",
                    },
                )
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="approval_invalid",
                    error_message="The approval is invalid, expired, or already consumed.",
                )
            approval_consumed = True

        final_decision = self.permission_manager.authorize(access)
        self.audit_service.record(
            event_type="permission_recheck",
            request_id=request_id,
            outcome=final_decision.effect.value,
            subject=access.subject,
            resource=access.resource,
            operation=access.operation,
            metadata={
                "tool_id": definition.tool_id,
                "reason_code": final_decision.reason_code,
                "grant_id": final_decision.grant_id or "",
                "decision": final_decision.effect.value,
            },
        )
        if final_decision.effect is DecisionEffect.DENY:
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="permission_denied",
                error_message="Permission was revoked or became unavailable before execution.",
            )
        if final_decision.effect is DecisionEffect.REQUIRE_APPROVAL and not approval_consumed:
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="approval_required",
                error_message="The latest permission policy requires human approval.",
            )

        handler = self.registry._resolve_handler(definition.tool_id, definition.version)
        started = time.monotonic()
        try:
            output = await asyncio.wait_for(
                handler(input_data),
                timeout=definition.timeout_seconds,
            )
            normalized_output = self.registry.validate_output(definition, output)
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            output_bytes = len(json.dumps(
                normalized_output, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8"))
            try:
                self.audit_service.record(
                    event_type="tool_execution",
                    request_id=request_id,
                    outcome="succeeded",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={
                        "tool_id": definition.tool_id,
                        "tool_version": definition.version,
                        "duration_ms": duration_ms,
                        "output_bytes": output_bytes,
                        "status": "succeeded",
                    },
                )
            except Exception:
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="audit_persistence_failed",
                    error_message="The action completed but its audit event could not be persisted.",
                    duration_ms=duration_ms,
                    side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
                )
            return ToolExecutionResult(
                True, definition.tool_id, definition.version, request_id,
                output=normalized_output,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            try:
                self.audit_service.record(
                    event_type="tool_execution",
                    request_id=request_id,
                    outcome="timed_out",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={
                        "tool_id": definition.tool_id,
                        "tool_version": definition.version,
                        "duration_ms": duration_ms,
                        "timeout_ms": definition.timeout_seconds * 1000,
                        "exception_type": "TimeoutError",
                    },
                )
            except Exception:
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="audit_persistence_failed",
                    error_message="The tool timed out and its audit event could not be persisted.",
                    duration_ms=duration_ms,
                    side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
                )
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="tool_timeout",
                error_message="The tool exceeded its execution time limit.",
                duration_ms=duration_ms,
                side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
            )
        except ToolInputValidationError as exc:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            try:
                self.audit_service.record(
                    event_type="tool_execution",
                    request_id=request_id,
                    outcome="invalid_output",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={
                        "tool_id": definition.tool_id,
                        "tool_version": definition.version,
                        "duration_ms": duration_ms,
                        "exception_type": type(exc).__name__,
                    },
                )
            except Exception:
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="audit_persistence_failed",
                    error_message="The tool output was invalid and its audit event could not be persisted.",
                    duration_ms=duration_ms,
                    side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
                )
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="tool_output_invalid",
                error_message=str(exc),
                duration_ms=duration_ms,
                side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
            )
        except asyncio.CancelledError:
            try:
                self.audit_service.record(
                    event_type="tool_execution",
                    request_id=request_id,
                    outcome="cancelled",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={"tool_id": definition.tool_id, "exception_type": "CancelledError"},
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            try:
                self.audit_service.record(
                    event_type="tool_execution",
                    request_id=request_id,
                    outcome="failed",
                    subject=access.subject,
                    resource=access.resource,
                    operation=access.operation,
                    metadata={
                        "tool_id": definition.tool_id,
                        "tool_version": definition.version,
                        "duration_ms": duration_ms,
                        "exception_type": type(exc).__name__,
                        "handler_category": "handler_error",
                    },
                )
            except Exception:
                return ToolExecutionResult(
                    False, definition.tool_id, definition.version, request_id,
                    error_category="audit_persistence_failed",
                    error_message="The tool failed and its audit event could not be persisted.",
                    duration_ms=duration_ms,
                    side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
                )
            return ToolExecutionResult(
                False, definition.tool_id, definition.version, request_id,
                error_category="tool_execution_failed",
                error_message="The registered tool handler failed.",
                duration_ms=duration_ms,
                side_effect_may_have_occurred=definition.risk_class is not ToolRiskClass.READ_ONLY,
            )

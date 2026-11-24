"""Explicit allow policy helpers for isolated service unit tests only."""
from core.permissions.manager import PermissionManager
from core.permissions.types import (
    AccessContext,
    DecisionEffect,
    PermissionDecision,
    PermissionScope,
    PermissionSubject,
    ScopeType,
    SubjectType,
)


class AllowTestPolicy:
    def evaluate(self, request):
        return PermissionDecision(
            DecisionEffect.ALLOW,
            "test_only_allow_policy",
            request.request_id,
        )


def make_test_access():
    context = AccessContext(
        subject=PermissionSubject(SubjectType.SERVICE, "unit-test-service"),
        scope=PermissionScope(ScopeType.LOCAL, "test-machine", "test-owner"),
    )
    manager = PermissionManager(policies=(AllowTestPolicy(),))
    return manager, context

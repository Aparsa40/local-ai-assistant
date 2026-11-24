"""Typed contracts and policy hooks for application-owned permissions."""

from .types import (
    AccessRequest,
    ApprovalRequest,
    ApprovalStatus,
    DataSensitivity,
    DecisionEffect,
    PermissionDecision,
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from .policies import DenyAllGrantAdministrationPolicy, GrantAdministrationPolicy

__all__ = [
    "AccessRequest",
    "ApprovalRequest",
    "ApprovalStatus",
    "DataSensitivity",
    "DecisionEffect",
    "PermissionDecision",
    "PermissionGrant",
    "PermissionOperation",
    "PermissionResource",
    "PermissionScope",
    "PermissionSubject",
    "ResourceType",
    "ScopeType",
    "SubjectType",
    "DenyAllGrantAdministrationPolicy",
    "GrantAdministrationPolicy",
]

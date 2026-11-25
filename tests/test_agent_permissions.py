"""WP-6.6 and WP-6.7 regression tests for agent capability binding and grants."""
from __future__ import annotations

import pytest

from agent_test_models import OWNER_ID, make_agent_env, make_definition
from core.agents.builtins import AGENT_ID, AGENT_VERSION, KNOWLEDGE_SEARCH_TOOL_ID
from core.agents.contracts import AgentRunStatus
from core.agents.context import AgentScopeDeniedError
from core.permissions.types import (
    PermissionGrant,
    PermissionOperation,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.repositories.permission_repository import PermissionRepository


def builtin_task(env, *, data_scopes):
    return env.services.lifecycle.create_task(
        agent_id=AGENT_ID,
        agent_version=AGENT_VERSION,
        owner_id=OWNER_ID,
        title="Permission probe",
        payload={"query": "durable storage"},
        data_scopes=data_scopes,
    )


def issue_through_the_controller(env, task):
    run = env.services.lifecycle.create_run(task.task_id)
    return env.execute(run.run_id)


def grants_for(env, run_id, scope_id):
    repository = PermissionRepository(env.session)
    nowish = _aware_now()
    scope = PermissionScope(ScopeType.USER, scope_id, OWNER_ID)
    return repository.list_exact(
        PermissionSubject(SubjectType.AGENT_RUN, run_id),
        PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope_id),
        PermissionOperation.READ,
        scope,
    )


def _aware_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def test_capability_grants_are_exact_read_only_and_per_run(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        scope = env.knowledge_scope()
        env.seed_knowledge(
            scope,
            "SQLite provides durable local storage. Knowledge retrieval uses lexical search.",
        )
        scope_id = scope.scope_id
        task = builtin_task(env, data_scopes=(env.data_scope(scope_id),))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED

        issued = grants_for(env, run.run_id, scope_id)
        assert len(issued) == 1
        grant = issued[0]
        assert grant.subject == PermissionSubject(SubjectType.AGENT_RUN, run.run_id)
        assert grant.operation is PermissionOperation.READ
        assert grant.resource == PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope_id)
        assert grant.scope.owner_id == OWNER_ID
        assert grant.issued_by == OWNER_ID
        assert grant.requires_approval is False
        assert grant.is_active(_aware_now())

        # Least privilege: no other scope, subject, or operation was granted.
        other_scope_grants = grants_for(env, run.run_id, "other-scope")
        assert other_scope_grants == ()
        write_grants = PermissionRepository(env.session).list_exact(
            PermissionSubject(SubjectType.AGENT_RUN, run.run_id),
            PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope_id),
            PermissionOperation.CREATE,
            PermissionScope(ScopeType.USER, scope_id, OWNER_ID),
        )
        assert write_grants == ()
        user_grants = PermissionRepository(env.session).list_exact(
            PermissionSubject(SubjectType.USER, OWNER_ID),
            PermissionResource(ResourceType.KNOWLEDGE_SOURCE, scope_id),
            PermissionOperation.READ,
            PermissionScope(ScopeType.USER, scope_id, OWNER_ID),
        )
        assert user_grants == ()
    finally:
        env.dispose()


def test_a_second_run_does_not_reuse_the_first_runs_grant(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        scope = env.knowledge_scope()
        env.seed_knowledge(scope, "Durable storage facts for the second run.")
        scope_id = scope.scope_id
        data_scope = env.data_scope(scope_id)

        first = builtin_task(env, data_scopes=(data_scope,))
        first_run = env.services.lifecycle.create_run(first.task_id)
        assert env.execute(first_run.run_id).status is AgentRunStatus.SUCCEEDED

        second = builtin_task(env, data_scopes=(data_scope,))
        second_run = env.services.lifecycle.create_run(second.task_id)
        assert env.execute(second_run.run_id).status is AgentRunStatus.SUCCEEDED

        first_grants = grants_for(env, first_run.run_id, scope_id)
        second_grants = grants_for(env, second_run.run_id, scope_id)
        assert len(first_grants) == 1
        assert len(second_grants) == 1
        assert first_grants[0].grant_id != second_grants[0].grant_id
        assert first_grants[0].subject != second_grants[0].subject
    finally:
        env.dispose()


def test_agent_subjects_cannot_issue_or_revoke_grants(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        manager = env.services.permission_manager
        scope = PermissionScope(ScopeType.USER, "scope-x", OWNER_ID)
        grant = PermissionGrant(
            grant_id="g" * 32,
            subject=PermissionSubject(SubjectType.AGENT_RUN, "1" * 32),
            resource=PermissionResource(ResourceType.KNOWLEDGE_SOURCE, "scope-x"),
            operation=PermissionOperation.READ,
            scope=scope,
            issued_by=OWNER_ID,
        )
        from core.permissions.manager import PermissionManagementDeniedError

        with pytest.raises(PermissionManagementDeniedError, match="Agent subjects"):
            manager.issue_grant(
                grant,
                issuer=PermissionSubject(SubjectType.AGENT_RUN, "1" * 32),
            )
        with pytest.raises(PermissionManagementDeniedError, match="Agent subjects"):
            manager.revoke_grant("g" * 32, issuer=PermissionSubject(SubjectType.AGENT_TYPE, "x"))
    finally:
        env.dispose()


def test_issuer_identity_mismatch_is_denied(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        manager = env.services.permission_manager
        grant = PermissionGrant(
            grant_id="h" * 32,
            subject=PermissionSubject(SubjectType.AGENT_RUN, "1" * 32),
            resource=PermissionResource(ResourceType.KNOWLEDGE_SOURCE, "scope-x"),
            operation=PermissionOperation.READ,
            scope=PermissionScope(ScopeType.USER, "scope-x", OWNER_ID),
            issued_by=OWNER_ID,
        )
        from core.permissions.manager import PermissionManagementDeniedError

        with pytest.raises(PermissionManagementDeniedError, match="identity"):
            manager.issue_grant(
                grant,
                issuer=PermissionSubject(SubjectType.USER, "somebody-else"),
            )
    finally:
        env.dispose()


def test_scoped_context_assembly_fails_closed_without_a_grant(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        # A definition without allowed tools receives no grants, so the
        # declared knowledge scope must fail closed at context assembly.
        definition = make_definition(allowed_tools=())
        env.services.registry.register(definition)
        task = env.services.lifecycle.create_task(
            agent_id=definition.agent_id,
            agent_version=definition.version,
            owner_id=OWNER_ID,
            title="Closed run",
            payload={},
            data_scopes=(env.data_scope(),),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        # The coroutine must actually run: an un-awaited call would silently
        # skip every assertion below.
        with pytest.raises(AgentScopeDeniedError):
            env.execute(run.run_id)
        live = env.services.lifecycle.get_run(run.run_id)
        # Fail closed: the run ends truthfully, the executor claim is released,
        # and no knowledge grant for the declared scope exists.
        assert live.status is AgentRunStatus.FAILED
        assert live.error_code == "context_or_capability_error"
        assert env.services.lifecycle.has_executor(run.run_id) is False
        assert grants_for(env, run.run_id, "agent-scope") == ()
    finally:
        env.dispose()


def test_capability_binding_is_least_privilege_and_public(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,))
        env.services.registry.register(definition)
        task = builtin_task(env, data_scopes=(env.data_scope(),))
        run = env.services.lifecycle.create_run(task.task_id)
        binding = env.services.controller.capability_resolver.resolve(
            definition, run, task
        )
        assert len(binding.capabilities) == 1
        capability = binding.capabilities[0]
        assert capability.tool_id == KNOWLEDGE_SEARCH_TOOL_ID
        assert capability.operation is PermissionOperation.READ
        assert capability.resource_type is ResourceType.KNOWLEDGE_SOURCE
        assert capability.risk_class == "read_only"
        # The binding is plain data: no handlers, sessions, or credentials.
        view = binding.public_view()
        assert view["capabilities"][0].keys() == {
            "tool_id", "version", "resource_type", "operation", "risk_class",
        }
    finally:
        env.dispose()

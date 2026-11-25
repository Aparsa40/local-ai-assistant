"""WP-6.4 and WP-6.5 / WP-6.7 regression tests for the bounded execution loop."""
from __future__ import annotations

import asyncio

import pytest

from agent_test_models import (
    OWNER_ID,
    ScriptedBehavior,
    compose_on,
    make_agent_env,
    make_definition,
    make_search_input,
)
from core.agents.builtins import AGENT_ID, AGENT_VERSION, KNOWLEDGE_SEARCH_TOOL_ID
from core.agents.controller import AgentControllerError
from core.agents.context import AgentScopeDeniedError
from core.agents.contracts import AgentRunStatus, StopReason, TaskStatus
from core.tools.schemas import ToolExecutionResult


def builtin_task(env, *, data_scopes, payload=None):
    return env.services.lifecycle.create_task(
        agent_id=AGENT_ID,
        agent_version=AGENT_VERSION,
        owner_id=OWNER_ID,
        title="Analyze the bound scope",
        payload=payload if payload is not None else {"query": "durable storage"},
        data_scopes=data_scopes,
    )


def scripted_task(env, definition, *, payload=None, data_scopes=()):
    env.services.registry.register(definition)
    env.services.controller.behaviors[(definition.agent_id, definition.version)] = (
        ScriptedBehavior([])
    )
    return env.services.lifecycle.create_task(
        agent_id=definition.agent_id,
        agent_version=definition.version,
        owner_id=OWNER_ID,
        title="Scripted run",
        payload=payload if payload is not None else {},
        data_scopes=data_scopes,
    )


def set_behavior(env, definition, behavior):
    env.services.controller.behaviors[(definition.agent_id, definition.version)] = behavior


def cleanup_orphan_run(env, run_id):
    env.services.lifecycle.release_executor(run_id)
    run = env.services.lifecycle.get_run(run_id)
    if run.status in (AgentRunStatus.PENDING, AgentRunStatus.RUNNING, AgentRunStatus.PAUSED):
        env.services.lifecycle.cancel(run_id, expected_version=run.version)


def observed_steps(env, run_id, kind):
    return [
        event for event in env.run_events(run_id)
        if event["event_type"] == "step_observed"
        and event["metadata"].get("kind") == kind
    ]


def test_builtin_agent_completes_with_searched_sources(tmp_path):
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
        assert final.stop_reason is StopReason.COMPLETED
        completion = final.outcome["completion"]
        assert completion["status"] == "complete"
        assert completion["criteria_met"] is True
        assert final.outcome["count"] >= 1
        assert final.outcome["results"][0]["content"]
        assert final.outcome["summary"] == "Knowledge scope analysis completed."
        # The deterministic agent must not use the model path at all.
        assert env.interface_manager.calls == []
        types = env.event_types(run.run_id)
        assert "run_created" in types
        assert "run_started" in types
        assert "capability_grants_issued" in types
        assert "step_observed" in types
        assert "run_completed" in types
        assert env.services.lifecycle.get_task(task.task_id).status is TaskStatus.COMPLETED
        checkpoints = env.checkpoints(run.run_id)
        assert checkpoints
        assert all(item.payload["schema"] == "agent.checkpoint/1" for item in checkpoints)
        assert any("observations" in item.payload for item in checkpoints)
    finally:
        env.dispose()


def test_builtin_agent_reports_empty_scopes_truthfully(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        scope = env.knowledge_scope("empty-scope")
        scope_id = scope.scope_id
        task = builtin_task(env, data_scopes=(env.data_scope(scope_id),))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)

        assert final.status is AgentRunStatus.SUCCEEDED
        completion = final.outcome["completion"]
        # The search succeeded but produced no sources: completion is not claimed.
        assert completion["status"] == "incomplete"
        assert completion["criteria_met"] is False
        assert final.outcome["count"] == 0
    finally:
        env.dispose()


def test_builtin_agent_reports_tool_failures_truthfully(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        scope = env.knowledge_scope("failing-scope")
        scope_id = scope.scope_id
        task = builtin_task(env, data_scopes=(env.data_scope(scope_id),))

        class FailingToolRuntime:
            async def execute(self, request):
                return ToolExecutionResult(
                    False,
                    request.tool_id,
                    request.version,
                    request.access_request.request_id,
                    error_category="tool_execution_failed",
                    error_message="The registered tool handler failed.",
                )

        from core.agents.controller import ExecutionController

        controller = ExecutionController(
            env.services.lifecycle,
            env.services.registry,
            env.services.runs,
            env.services.checkpoints,
            env.services.events,
            FailingToolRuntime(),
            env.services.controller.capability_resolver,
            env.services.controller.context_builder,
            env.services.controller.evaluator,
            interface_manager=env.interface_manager,
            behaviors=env.services.controller.behaviors,
            managed_permission_manager=env.services.permission_manager,
            audit_service=env.services.audit_service,
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = asyncio.run(controller.execute(run.run_id))

        assert final.status is AgentRunStatus.SUCCEEDED
        assert final.outcome["completion"]["status"] == "incomplete"
        assert final.outcome["reason_code"] == "tool_execution_failed"
        failed_observations = [
            event for event in env.run_events(run.run_id)
            if event["event_type"] == "step_observed" and event["outcome"] == "failed"
        ]
        assert failed_observations
    finally:
        env.dispose()


def test_run_identity_mismatch_is_denied(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,))
        task = scripted_task(env, definition, data_scopes=(env.data_scope(),))

        class ForgedRunBehavior(ScriptedBehavior):
            def decide(self, ctx, state):
                return {
                    "kind": "tool",
                    "tool_id": KNOWLEDGE_SEARCH_TOOL_ID,
                    "input": make_search_input("0" * 32, env.knowledge_scope()),
                }

        set_behavior(env, definition, ForgedRunBehavior([]))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)

        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.PERMISSION_DENIED
        assert final.error_code == "run_identity_mismatch"
        assert env.events_of_type(run.run_id, "run_failed")
    finally:
        env.dispose()


def test_unbound_scope_proposals_are_denied(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,))
        task = scripted_task(env, definition, data_scopes=(env.data_scope(),))

        class OtherScopeBehavior(ScriptedBehavior):
            def decide(self, ctx, state):
                return {
                    "kind": "tool",
                    "tool_id": KNOWLEDGE_SEARCH_TOOL_ID,
                    "input": make_search_input(ctx.run_id, env.knowledge_scope("other-scope")),
                }

        set_behavior(env, definition, OtherScopeBehavior([]))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)

        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.PERMISSION_DENIED
        assert final.error_code == "scope_not_bound"
    finally:
        env.dispose()


def test_unbound_capabilities_are_denied(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=())
        task = scripted_task(env, definition)

        class GhostToolBehavior(ScriptedBehavior):
            def decide(self, ctx, state):
                return {
                    "kind": "tool",
                    "tool_id": "ghost_tool",
                    "input": {"run_id": ctx.run_id},
                }

        set_behavior(env, definition, GhostToolBehavior([]))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)

        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.PERMISSION_DENIED
        assert final.error_code == "capability_not_bound"
    finally:
        env.dispose()


def test_runs_without_declared_tools_fail_scoped_context_assembly(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=())
        task = scripted_task(env, definition, data_scopes=(env.data_scope(),))
        run = env.services.lifecycle.create_run(task.task_id)
        with pytest.raises(AgentScopeDeniedError):
            env.execute(run.run_id)
        live = env.services.lifecycle.get_run(run.run_id)
        # Fail closed: the run must end truthfully instead of continuing.
        assert live.status is AgentRunStatus.FAILED
        assert live.error_code == "context_or_capability_error"
        assert env.services.lifecycle.has_executor(run.run_id) is False
    finally:
        env.dispose()


def test_mutating_tool_bindings_are_rejected_for_this_phase(tmp_path):
    from core.permissions.types import PermissionOperation, ResourceType
    from core.tools.schemas import ToolDefinition, ToolRiskClass

    env = make_agent_env(tmp_path)
    try:
        env.container.tool_registry.register(
            ToolDefinition(
                tool_id="notes_writer",
                version="1.0.0",
                input_schema={"type": "object"},
                resource_type=ResourceType.KNOWLEDGE_SOURCE,
                operation=PermissionOperation.CREATE,
                risk_class=ToolRiskClass.MUTATING,
                requires_approval=True,
            ),
            _notes_writer_handler,
        )
        definition = make_definition(allowed_tools=("notes_writer",))
        task = scripted_task(env, definition)
        run = env.services.lifecycle.create_run(task.task_id)
        with pytest.raises(AgentScopeDeniedError, match="read-only"):
            env.execute(run.run_id)
        live = env.services.lifecycle.get_run(run.run_id)
        assert live.status is AgentRunStatus.FAILED
        assert live.error_code == "context_or_capability_error"
        assert env.services.lifecycle.has_executor(run.run_id) is False
    finally:
        env.dispose()


async def _notes_writer_handler(input_data: dict) -> dict:
    return {"written": True}


def test_finished_runs_cannot_be_executed_again(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_tools=())
        task = scripted_task(env, definition)
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {"kind": "finish", "status": "complete", "outcome": {"result": {"value": 1}}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED
        with pytest.raises(AgentControllerError, match="finished"):
            env.execute(run.run_id)
    finally:
        env.dispose()


def test_run_without_a_trusted_behavior_is_rejected(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition()
        env.services.registry.register(definition)
        task = env.services.lifecycle.create_task(
            agent_id=definition.agent_id,
            agent_version=definition.version,
            owner_id=OWNER_ID,
            title="Orphan behavior",
            payload={},
        )
        run = env.services.lifecycle.create_run(task.task_id)
        with pytest.raises(AgentControllerError, match="behavior"):
            env.execute(run.run_id)
        cleanup_orphan_run(env, run.run_id)
    finally:
        env.dispose()


def test_model_route_allowlist_blocks_unlisted_models(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_models=("ollama/other-model",))
        task = scripted_task(
            env, definition, payload={"allow_model_transmission": True},
        )
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {
                    "kind": "model",
                    "provider_id": "ollama",
                    "model_id": "test-model",
                    "prompt": "hello",
                    "estimated_prompt_tokens": 3,
                },
                {"kind": "finish", "status": "complete", "outcome": {"result": "observed"}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED
        assert env.interface_manager.calls == []
        model_steps = observed_steps(env, run.run_id, "model")
        assert model_steps and model_steps[0]["outcome"] == "failed"
        assert final.model_tokens == 0
    finally:
        env.dispose()


def test_model_transmission_requires_task_level_authorization(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(allowed_models=("ollama/test-model",))
        task = scripted_task(env, definition, payload={})  # no explicit authorization
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {
                    "kind": "model",
                    "provider_id": "ollama",
                    "model_id": "test-model",
                    "prompt": "hello",
                    "estimated_prompt_tokens": 3,
                },
                {"kind": "finish", "status": "complete", "outcome": {"result": "blocked-then-done"}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED
        assert env.interface_manager.calls == []
    finally:
        env.dispose()


def make_budgets(**overrides):
    from core.agents.contracts import AgentBudgets

    values = dict(max_iterations=6, max_tool_calls=10, max_model_tokens=1000)
    values.update(overrides)
    return AgentBudgets(**values)


def test_zero_model_token_budget_blocks_provider_calls(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(
            allowed_models=("ollama/test-model",),
            budgets=make_budgets(max_model_tokens=0),
        )
        task = scripted_task(
            env, definition, payload={"allow_model_transmission": True},
        )
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {
                    "kind": "model",
                    "provider_id": "ollama",
                    "model_id": "test-model",
                    "prompt": "hello",
                    "estimated_prompt_tokens": 10,
                },
                {"kind": "finish", "status": "complete", "outcome": {"result": "unreachable"}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.TOKEN_BUDGET_EXHAUSTED
        assert env.interface_manager.calls == []
    finally:
        env.dispose()


def test_successful_model_calls_stream_via_the_interface_manager(tmp_path):
    env = make_agent_env(tmp_path)
    env.interface_manager.chunks = ("alpha ", "beta")
    try:
        definition = make_definition(
            allowed_models=("ollama/test-model",),
            budgets=make_budgets(max_model_tokens=1000),
        )
        task = scripted_task(
            env, definition, payload={"allow_model_transmission": True},
        )
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {
                    "kind": "model",
                    "provider_id": "ollama",
                    "model_id": "test-model",
                    "prompt": "report",
                    "estimated_prompt_tokens": 2,
                },
                {"kind": "finish", "status": "complete", "outcome": {"result": "alpha beta"}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED
        assert len(env.interface_manager.calls) == 1
        call = env.interface_manager.calls[0]
        assert call["provider_id"] == "ollama"
        assert call["model"] == "test-model"
        assert call["messages"][0]["content"].startswith("Agent goal: ")
        assert final.model_tokens >= 2
    finally:
        env.dispose()


def make_looping_behavior(env, scope):
    class LoopingBehavior(ScriptedBehavior):
        def decide(self, ctx, state):
            self.calls += 1
            return {
                "kind": "tool",
                "tool_id": KNOWLEDGE_SEARCH_TOOL_ID,
                "input": make_search_input(ctx.run_id, scope),
            }

    return LoopingBehavior([])


def test_iteration_budget_stops_repeating_behaviors(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(
            allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,),
            budgets=make_budgets(max_iterations=2),
        )
        task = scripted_task(
            env, definition, data_scopes=(env.data_scope(),),
            payload={"query": "durable storage"},
        )
        set_behavior(env, definition, make_looping_behavior(env, env.knowledge_scope()))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.MAX_ITERATIONS
        assert final.iteration == 2
    finally:
        env.dispose()


def test_tool_call_budget_brakes_runaway_tools(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        definition = make_definition(
            allowed_tools=(KNOWLEDGE_SEARCH_TOOL_ID,),
            budgets=make_budgets(max_tool_calls=1),
        )
        task = scripted_task(
            env, definition, data_scopes=(env.data_scope(),),
            payload={"query": "durable storage"},
        )
        set_behavior(env, definition, make_looping_behavior(env, env.knowledge_scope()))
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.FAILED
        assert final.stop_reason is StopReason.TOOL_CALL_LIMIT
        assert final.tool_calls == 1
    finally:
        env.dispose()


def test_paused_runs_with_unresolved_approvals_cannot_execute(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = builtin_task(env, data_scopes=(env.data_scope(),))
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        env.services.lifecycle.pause_for_approval(
            run.run_id, expected_version=started.version, approval_id="approval-1",
        )
        with pytest.raises(AgentControllerError, match="approval"):
            env.execute(run.run_id)
    finally:
        env.dispose()


def test_restart_recovery_does_not_reexecute_and_stays_paused(tmp_path):
    env = make_agent_env(tmp_path)
    db_path = env.engine.url.database
    try:
        task = builtin_task(env, data_scopes=(env.data_scope(),))
        run = env.services.lifecycle.create_run(task.task_id)
        env.services.lifecycle.start(run.run_id, expected_version=run.version)

        # A second composition over the same database simulates the post-restart
        # application: no in-process executor claims survive a restart.
        restarted = compose_on(db_path)
        try:
            assert restarted.container.recover_stale_runs() == 1
            recovered = restarted.services.lifecycle.get_run(run.run_id)
            assert recovered.status is AgentRunStatus.PAUSED
            assert recovered.error_code == "restart_recovery"
            assert restarted.container.recover_stale_runs() == 0
            assert restarted.services.lifecycle.get_run(run.run_id).iteration == 0
        finally:
            restarted.dispose()
    finally:
        env.dispose()


def test_model_unavailability_is_reported_as_an_incomplete_observation(tmp_path):
    env = make_agent_env(tmp_path)
    env.interface_manager.error = RuntimeError("ollama not running")
    try:
        definition = make_definition(
            allowed_models=("ollama/test-model",),
            budgets=make_budgets(max_model_tokens=1000),
        )
        task = scripted_task(
            env, definition, payload={"allow_model_transmission": True},
        )
        set_behavior(
            env, definition,
            ScriptedBehavior([
                {
                    "kind": "model",
                    "provider_id": "ollama",
                    "model_id": "test-model",
                    "prompt": "report",
                    "estimated_prompt_tokens": 2,
                },
                {"kind": "finish", "status": "incomplete", "outcome": {"result": ""}},
            ]),
        )
        run = env.services.lifecycle.create_run(task.task_id)
        final = env.execute(run.run_id)
        assert final.status is AgentRunStatus.SUCCEEDED
        assert final.outcome["completion"]["status"] == "incomplete"
        assert len(env.interface_manager.calls) == 1
        model_steps = observed_steps(env, run.run_id, "model")
        assert model_steps and model_steps[0]["outcome"] == "failed"
    finally:
        env.dispose()

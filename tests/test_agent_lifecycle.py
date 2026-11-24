"""WP-6.3 / WP-6.7 regression tests for deterministic run lifecycle management."""
from __future__ import annotations

import pytest

from agent_test_models import (
    OWNER_ID,
    make_agent_env,
)
from core.agents.builtins import AGENT_ID, AGENT_VERSION
from core.agents.contracts import (
    AgentConcurrencyError,
    AgentError,
    AgentRunStatus,
    AgentTransitionError,
    StopReason,
    TaskStatus,
)


def make_task(env, *, data_scopes=(), payload=None):
    return env.services.lifecycle.create_task(
        agent_id=AGENT_ID,
        agent_version=AGENT_VERSION,
        owner_id=OWNER_ID,
        title="Lifecycle probe",
        payload=payload if payload is not None else {"query": "durable storage"},
        data_scopes=data_scopes,
    )


def test_create_task_rejects_unknown_agents(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        with pytest.raises(AgentError, match="unknown"):
            env.services.lifecycle.create_task(
                agent_id="no-such-agent",
                agent_version="1.0.0",
                owner_id=OWNER_ID,
                title="Bad task",
                payload={},
            )
        assert env.services.tasks.list_recent() == ()
    finally:
        env.dispose()


def test_create_run_persists_pending_state_and_audits_creation(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        assert run.status is AgentRunStatus.PENDING
        assert run.version == 1
        assert run.attempt == 1
        assert run.owner_id == OWNER_ID
        assert run.scope_type == "task"
        assert run.scope_id == task.task_id
        assert env.events_of_type(run.run_id, "run_created")
        assert run.run_id.startswith("run:") is False  # 32-character hex id
        assert len(run.run_id) == 32
    finally:
        env.dispose()


def test_start_pause_resume_cycle_is_audited_and_accumulates_attempts(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        assert started.status is AgentRunStatus.RUNNING
        assert started.started_at is not None
        assert env.events_of_type(run.run_id, "run_started")

        paused = env.services.lifecycle.pause(
            run.run_id, expected_version=started.version,
            reason=StopReason.PAUSED_BY_REQUEST,
        )
        assert paused.status is AgentRunStatus.PAUSED
        assert paused.stop_reason is StopReason.PAUSED_BY_REQUEST
        assert env.services.lifecycle.has_executor(run.run_id) is False

        resumed = env.services.lifecycle.resume(
            run.run_id, expected_version=paused.version,
        )
        assert resumed.status is AgentRunStatus.RUNNING
        assert resumed.attempt == 2
        assert resumed.stop_reason is None
        assert env.events_of_type(run.run_id, "run_resumed")
    finally:
        env.dispose()


def test_stale_expected_versions_are_rejected_with_concurrency_errors(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        with pytest.raises(AgentConcurrencyError):
            env.services.lifecycle.start(run.run_id, expected_version=run.version - 1)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        with pytest.raises(AgentConcurrencyError):
            env.services.lifecycle.pause(
                run.run_id, expected_version=started.version - 1,
                reason=StopReason.PAUSED_BY_REQUEST,
            )
    finally:
        env.dispose()


def test_start_twice_is_not_a_legal_transition(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        with pytest.raises(AgentTransitionError):
            env.services.lifecycle.start(run.run_id, expected_version=started.version)
    finally:
        env.dispose()


def test_executor_claims_are_exclusive_in_process(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        env.services.lifecycle.claim_executor(run.run_id)
        assert env.services.lifecycle.has_executor(run.run_id)
        with pytest.raises(AgentConcurrencyError, match="executor"):
            env.services.lifecycle.claim_executor(run.run_id)
        env.services.lifecycle.release_executor(run.run_id)
        env.services.lifecycle.claim_executor(run.run_id)
    finally:
        env.dispose()


def test_pause_requires_a_truthful_pause_reason(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        with pytest.raises(ValueError, match="truthful pause reason"):
            env.services.lifecycle.pause(
                run.run_id, expected_version=started.version,
                reason=StopReason.COMPLETED,
            )
    finally:
        env.dispose()


def test_approval_pointer_blocks_resume_until_cleared(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)
        paused = env.services.lifecycle.pause_for_approval(
            run.run_id, expected_version=started.version, approval_id="approval-1",
        )
        assert paused.status is AgentRunStatus.PAUSED
        assert paused.pending_approval_id == "approval-1"
        assert paused.stop_reason is StopReason.PAUSED_FOR_APPROVAL
        assert env.events_of_type(run.run_id, "run_paused_for_approval")

        with pytest.raises(AgentError, match="unresolved approval"):
            env.services.lifecycle.resume(
                run.run_id, expected_version=paused.version,
            )
        cleared = env.services.lifecycle.clear_pending_approval(
            run.run_id, expected_version=paused.version,
        )
        assert cleared.pending_approval_id is None
        assert env.events_of_type(run.run_id, "approval_cleared")
        resumed = env.services.lifecycle.resume(
            run.run_id, expected_version=cleared.version,
        )
        assert resumed.status is AgentRunStatus.RUNNING
        assert resumed.attempt == 2
    finally:
        env.dispose()


def test_clear_pending_approval_requires_a_pending_approval(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        with pytest.raises(AgentError, match="no pending approval"):
            env.services.lifecycle.clear_pending_approval(
                run.run_id, expected_version=run.version,
            )
    finally:
        env.dispose()


def test_cancel_is_legal_from_pending_and_running_but_not_terminal(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        first = env.services.lifecycle.create_run(task.task_id)
        cancelled = env.services.lifecycle.cancel(
            first.run_id, expected_version=first.version,
        )
        assert cancelled.status is AgentRunStatus.CANCELLED
        assert cancelled.stop_reason is StopReason.CANCELLED
        assert env.events_of_type(first.run_id, "run_cancelled")
        with pytest.raises(AgentTransitionError):
            env.services.lifecycle.cancel(
                first.run_id, expected_version=cancelled.version,
            )

        second = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(second.run_id, expected_version=1)
        cancelled_running = env.services.lifecycle.cancel(
            second.run_id, expected_version=started.version, reason="operator_shutdown",
        )
        assert cancelled_running.error_message == "operator_shutdown"
    finally:
        env.dispose()


def test_completion_and_failure_record_truthful_state(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        started = env.services.lifecycle.start(run.run_id, expected_version=run.version)

        completed = env.services.lifecycle.complete(
            run.run_id, expected_version=started.version,
            outcome={"summary": "done", "count": 2, "status": "completed"},
        )
        assert completed.status is AgentRunStatus.SUCCEEDED
        assert completed.stop_reason is StopReason.COMPLETED
        assert completed.outcome["count"] == 2
        assert completed.finished_at is not None
        assert env.events_of_type(run.run_id, "run_completed")
        assert env.services.lifecycle.get_task(task.task_id).status is TaskStatus.COMPLETED

        with pytest.raises(AgentTransitionError):
            env.services.lifecycle.fail(
                run.run_id, expected_version=completed.version,
                error_code="late_failure",
                error_message="Too late.",
                stop_reason=StopReason.FAILED,
            )

        failure = env.services.lifecycle.create_run(task.task_id)
        failure_started = env.services.lifecycle.start(
            failure.run_id, expected_version=failure.version,
        )
        failed = env.services.lifecycle.fail(
            failure.run_id, expected_version=failure_started.version,
            error_code="budget_exceeded",
            error_message="The run exceeded its iteration budget.",
            stop_reason=StopReason.MAX_ITERATIONS,
        )
        assert failed.status is AgentRunStatus.FAILED
        assert failed.error_code == "budget_exceeded"
        assert env.services.lifecycle.get_task(task.task_id).status is TaskStatus.FAILED

        with pytest.raises(ValueError, match="truthful failure stop reason"):
            env.services.lifecycle.fail(
                failure.run_id, expected_version=failed.version,
                error_code="not_truthful",
                error_message="Completed runs cannot fail.",
                stop_reason=StopReason.COMPLETED,
            )
    finally:
        env.dispose()


def test_recover_stale_runs_skips_live_executors_and_pauses_orphans(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)
        env.services.lifecycle.start(run.run_id, expected_version=run.version)

        # The live executor claim keeps the run untouched by recovery.
        assert env.services.lifecycle.recover_stale_runs() == 0
        assert env.services.lifecycle.get_run(run.run_id).status is AgentRunStatus.RUNNING

        env.services.lifecycle.release_executor(run.run_id)
        recovered = env.services.lifecycle.recover_stale_runs()
        assert recovered == 1
        recovered_run = env.services.lifecycle.get_run(run.run_id)
        assert recovered_run.status is AgentRunStatus.PAUSED
        assert recovered_run.error_code == "restart_recovery"
        assert recovered_run.outcome is None
        assert env.events_of_type(run.run_id, "run_recovered")

        # Recovery is idempotent: no RUNNING runs remain.
        assert env.services.lifecycle.recover_stale_runs() == 0
    finally:
        env.dispose()


def test_unknown_runs_raise_lookup_errors(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        with pytest.raises(AgentError, match="not found|unknown|Run was not"):
            env.services.lifecycle.get_run("0" * 32)
        task = make_task(env)
        with pytest.raises(AgentError, match="not found|unknown|Task was not"):
            env.services.lifecycle.create_run("0" * 31)
        assert task.task_id
    finally:
        env.dispose()


def test_event_persistence_failures_surface_instead_of_being_swallowed(tmp_path):
    env = make_agent_env(tmp_path)
    try:
        task = make_task(env)
        run = env.services.lifecycle.create_run(task.task_id)

        class FailingAppend:
            def append(self, event):
                raise RuntimeError("disk full")

        original = env.services.events.repository
        env.services.events.repository = FailingAppend()
        try:
            with pytest.raises(AgentError, match="event could not be persisted"):
                env.services.lifecycle.start(run.run_id, expected_version=run.version)
        finally:
            env.services.events.repository = original
        # The transition persisted, but the missing event is surfaced loudly and
        # no executor claim leaks; the caller must inspect the run before relying
        # on the result.
        assert env.services.lifecycle.get_run(run.run_id).status is AgentRunStatus.RUNNING
        assert env.services.lifecycle.has_executor(run.run_id) is False
    finally:
        env.dispose()

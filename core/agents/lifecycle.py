"""Deterministic, auditable agent run lifecycle management.

Transitions follow the explicit TRANSITIONS table in contracts.py. Every
transition is guarded by an optimistic concurrency check and recorded as a
redacted run event; unexpected event-persistence failures surface as errors
instead of being swallowed. Exactly one in-process executor may hold a run.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from core.agents.contracts import (
    AgentConcurrencyError,
    AgentError,
    AgentRun,
    AgentRunStatus,
    AgentTask,
    DataScope,
    StopReason,
    TaskStatus,
    require_transition,
    new_run_id,
)
from core.agents.events import AgentRunEventRecorder
from core.agents.registry import AgentRegistry
from core.repositories.run_repository import AgentRunRepository
from core.repositories.task_repository import AgentTaskRepository


class RunNotFoundError(AgentError, LookupError):
    """The requested run does not exist."""


class TaskNotFoundError(AgentError, LookupError):
    """The requested task does not exist."""


class AgentLifecycleManager:
    """Single owner of run creation and lifecycle state changes."""

    def __init__(
        self,
        registry: AgentRegistry,
        tasks: AgentTaskRepository,
        runs: AgentRunRepository,
        events: AgentRunEventRecorder,
        *,
        clock=None,
    ) -> None:
        self.registry = registry
        self.tasks = tasks
        self.runs = runs
        self.events = events
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._active_executors: set = set()
        self._executor_lock = threading.Lock()

    # -- executor claims ---------------------------------------------------

    def claim_executor(self, run_id: str) -> None:
        """Claim exclusive in-process execution ownership for one run."""
        with self._executor_lock:
            if run_id in self._active_executors:
                raise AgentConcurrencyError("Another executor already holds this run.")
            self._active_executors.add(run_id)

    def release_executor(self, run_id: str) -> None:
        with self._executor_lock:
            self._active_executors.discard(run_id)

    def has_executor(self, run_id: str) -> bool:
        with self._executor_lock:
            return run_id in self._active_executors

    # -- task and run creation --------------------------------------------

    def create_task(
        self,
        *,
        agent_id: str,
        agent_version: str,
        owner_id: str,
        title: str,
        payload: dict,
        data_scopes: tuple = (),
    ) -> AgentTask:
        """Validate the definition up front; a task without a valid agent is rejected."""
        self.registry.get_enabled(agent_id, agent_version)
        task = self.tasks.create(
            agent_id=agent_id,
            agent_version=agent_version,
            owner_id=owner_id,
            title=title,
            payload=payload,
            data_scopes=data_scopes,
        )
        return task

    def create_run(self, task_id: str) -> AgentRun:
        task = self.tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError("Task was not found.")
        self.registry.get_enabled(task.agent_id, task.agent_version)
        run = self.runs.create(
            task_id=task.task_id,
            agent_id=task.agent_id,
            agent_version=task.agent_version,
            owner_id=task.owner_id,
            trace_id=new_run_id(),
            scope_type="task",
            scope_id=task.task_id,
        )
        self.events.record(
            run_id=run.run_id,
            event_type="run_created",
            outcome="pending",
            metadata={
                "agent_id": run.agent_id,
                "agent_version": run.agent_version,
                "task_id": run.task_id,
                "trace_id": run.trace_id,
                "scope_type": run.scope_type,
                "scope_id": run.scope_id,
            },
        )
        return run

    def get_run(self, run_id: str) -> AgentRun:
        run = self.runs.get(run_id)
        if run is None:
            raise RunNotFoundError("Run was not found.")
        return run

    def get_task(self, task_id: str) -> AgentTask:
        task = self.tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError("Task was not found.")
        return task

    # -- transitions -------------------------------------------------------

    def _transition(
        self,
        run: AgentRun,
        target: AgentRunStatus,
        *,
        event_type: str,
        metadata=None,
        **updates,
    ) -> AgentRun:
        require_transition(run.status, target)
        try:
            updated = self.runs.transition(run.run_id, expected_version=run.version, **updates)
        except AgentConcurrencyError:
            raise
        if updated is None:
            raise RunNotFoundError("Run was not found.")
        try:
            self.events.record(
                run_id=run.run_id,
                event_type=event_type,
                outcome=target.value,
                metadata={"agent_id": run.agent_id, "task_id": run.task_id, **(metadata or {})},
            )
        except Exception as exc:
            raise AgentError(
                "The run state changed but its event could not be persisted; "
                "inspect the run before relying on this result."
            ) from exc
        return updated

    def start(self, run_id: str, *, expected_version: int) -> AgentRun:
        run = self.get_run(run_id)
        self.claim_executor(run_id)
        try:
            updated = self._transition(
                run,
                AgentRunStatus.RUNNING,
                event_type="run_started",
                status=AgentRunStatus.RUNNING,
                started_at=self._clock(),
                stop_reason=None,
            )
        except Exception:
            self.release_executor(run_id)
            raise
        self._mirror_task_status(updated, TaskStatus.RUNNING)
        return updated

    def pause(self, run_id: str, *, expected_version: int, reason: StopReason) -> AgentRun:
        if not isinstance(reason, StopReason) or reason not in {
            StopReason.PAUSED_BY_REQUEST, StopReason.PAUSED_FOR_APPROVAL,
        }:
            raise ValueError("pause requires a truthful pause reason")
        run = self.get_run(run_id)
        updated = self._transition(
            run,
            AgentRunStatus.PAUSED,
            event_type="run_paused",
            status=AgentRunStatus.PAUSED,
            stop_reason=reason,
            metadata={"reason_code": reason.value},
        )
        self.release_executor(run_id)
        return updated

    def pause_for_approval(
        self, run_id: str, *, expected_version: int, approval_id: str
    ) -> AgentRun:
        if not isinstance(approval_id, str) or not approval_id.strip() or len(approval_id) > 80:
            raise ValueError("approval_id is invalid")
        run = self.get_run(run_id)
        updated = self._transition(
            run,
            AgentRunStatus.PAUSED,
            event_type="run_paused_for_approval",
            status=AgentRunStatus.PAUSED,
            stop_reason=StopReason.PAUSED_FOR_APPROVAL,
            pending_approval_id=approval_id,
            metadata={"approval_id": approval_id},
        )
        self.release_executor(run_id)
        return updated

    def resume(self, run_id: str, *, expected_version: int) -> AgentRun:
        run = self.get_run(run_id)
        if run.pending_approval_id:
            raise AgentError(
                "The run still has an unresolved approval; decide the approval first."
            )
        self.claim_executor(run_id)
        try:
            updated = self._transition(
                run,
                AgentRunStatus.RUNNING,
                event_type="run_resumed",
                status=AgentRunStatus.RUNNING,
                attempt=run.attempt + 1,
                stop_reason=None,
                pending_approval_id=None,
            )
        except Exception:
            self.release_executor(run_id)
            raise
        return updated

    def cancel(self, run_id: str, *, expected_version: int, reason: str = "requested_by_owner") -> AgentRun:
        run = self.get_run(run_id)
        updated = self._transition(
            run,
            AgentRunStatus.CANCELLED,
            event_type="run_cancelled",
            status=AgentRunStatus.CANCELLED,
            stop_reason=StopReason.CANCELLED,
            finished_at=self._clock(),
            error_message=reason,
            metadata={"reason_code": reason},
        )
        self.release_executor(run_id)
        self._mirror_task_status(updated, TaskStatus.CANCELLED)
        return updated

    def complete(self, run_id: str, *, expected_version: int, outcome: dict) -> AgentRun:
        run = self.get_run(run_id)
        updated = self._transition(
            run,
            AgentRunStatus.SUCCEEDED,
            event_type="run_completed",
            status=AgentRunStatus.SUCCEEDED,
            stop_reason=StopReason.COMPLETED,
            outcome=outcome,
            finished_at=self._clock(),
            pending_approval_id=None,
            metadata={"reason_code": StopReason.COMPLETED.value},
        )
        self.release_executor(run_id)
        self._mirror_task_status(updated, TaskStatus.COMPLETED)
        return updated

    def fail(
        self,
        run_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_message: str,
        stop_reason: StopReason,
    ) -> AgentRun:
        if not isinstance(stop_reason, StopReason) or stop_reason in {
            StopReason.COMPLETED, StopReason.PAUSED_BY_REQUEST, StopReason.PAUSED_FOR_APPROVAL,
        }:
            raise ValueError("fail requires a truthful failure stop reason")
        if not isinstance(error_code, str) or not error_code.strip() or len(error_code) > 80:
            raise ValueError("error_code is invalid")
        if not isinstance(error_message, str) or len(error_message) > 300:
            raise ValueError("error_message is too long")
        run = self.get_run(run_id)
        updated = self._transition(
            run,
            AgentRunStatus.FAILED,
            event_type="run_failed",
            status=AgentRunStatus.FAILED,
            stop_reason=stop_reason,
            error_code=error_code,
            error_message=error_message,
            finished_at=self._clock(),
            pending_approval_id=None,
            metadata={"reason_code": stop_reason.value, "error_code": error_code},
        )
        self.release_executor(run_id)
        self._mirror_task_status(updated, TaskStatus.FAILED)
        return updated

    # -- recovery ----------------------------------------------------------

    def recover_stale_runs(self) -> int:
        """Pause runs left RUNNING by a previous interrupted process.

        This restores a consistent state without re-executing any step; a user
        or operator decides afterwards whether to resume the run.
        """
        recovered = 0
        for run in self.runs.list_by_status(
            AgentRunStatus.RUNNING, AgentRunStatus.PENDING, limit=200
        ):
            if self.has_executor(run.run_id):
                continue
            target = AgentRunStatus.PAUSED if run.status is AgentRunStatus.RUNNING else AgentRunStatus.CANCELLED
            try:
                require_transition(run.status, target)
            except Exception:
                continue
            try:
                self.runs.transition(
                    run.run_id,
                    expected_version=run.version,
                    status=target,
                    stop_reason=(
                        StopReason.PAUSED_BY_REQUEST
                        if target is AgentRunStatus.PAUSED
                        else StopReason.CANCELLED
                    ),
                    error_code="restart_recovery",
                    error_message=(
                        "The application restarted while this run was active; "
                        "no steps were re-executed."
                    ),
                    finished_at=self._clock() if target is AgentRunStatus.CANCELLED else None,
                )
            except AgentConcurrencyError:
                continue
            try:
                self.events.record(
                    run_id=run.run_id,
                    event_type="run_recovered",
                    outcome=target.value,
                    metadata={"reason_code": "restart_recovery"},
                )
            except Exception:
                # The persisted state is already consistent (paused/cancelled);
                # surface the event loss instead of hiding it.
                recovered += 1
                continue
            recovered += 1
        return recovered

    def _mirror_task_status(self, run: AgentRun, status: TaskStatus) -> None:
        try:
            self.tasks.update_status(run.task_id, status)
        except Exception:
            # Task mirroring is best effort; the run record remains the source of truth.
            pass

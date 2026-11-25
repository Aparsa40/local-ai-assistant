"""Bounded, auditable execution controller for agent runs.

Implements the deterministic plan/act/observe/evaluate loop. Model calls go
exclusively through InterfaceManager; tool calls go exclusively through
ToolRuntime with PermissionManager authorization. Every externally visible
change is checkpointed and recorded as a redacted run event, and every budget
violation stops the run with a truthful stop reason.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from core.agents.contracts import (
    AgentBudgets,
    AgentCheckpoint,
    AgentDefinition,
    AgentConcurrencyError,
    AgentError,
    AgentRun,
    AgentRunStatus,
    StopReason,
)
from core.agents.context import RunContext
from core.agents.events import AgentRunEventRecorder
from core.agents.lifecycle import AgentLifecycleManager
from core.agents.registry import AgentRegistry
from core.permissions.types import (
    AccessRequest,
    PermissionResource,
    PermissionScope,
    PermissionSubject,
    ResourceType,
    ScopeType,
    SubjectType,
)
from core.tools.schemas import ToolCallRequest


class AgentControllerError(AgentError):
    """The controller could not complete one bounded run."""


class AgentBudgetExceededError(AgentControllerError):
    """A declared budget ceiling was reached; the stop reason is truthful."""

    def __init__(self, stop_reason: StopReason, message: str) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason


def _json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str).encode("utf-8"))


def _bounded_observation(observation: dict, maximum: int = 2048) -> dict:
    if _json_bytes(observation) <= maximum:
        return observation
    truncated = dict(observation)
    truncated["truncated"] = True
    for key, value in list(truncated.items()):
        if isinstance(value, str) and len(value) > 256:
            truncated[key] = value[:256]
    if _json_bytes(truncated) > maximum:
        for key in list(truncated):
            if key not in {"kind", "ok", "error_category", "truncated"}:
                truncated.pop(key, None)
        truncated["summary"] = "observation detail exceeded the persistence bound"
    return truncated


class ExecutionController:
    """Drives one bounded run to a truthful, resumable outcome.

    Behaviors are trusted application classes registered by AgentRuntimeContainer.
    They receive only a RunContext and plain observation data; they never receive
    sessions, repositories, credentials, provider clients, or handler objects.
    """

    def __init__(
        self,
        lifecycle: AgentLifecycleManager,
        registry: AgentRegistry,
        runs,
        checkpoints,
        events: AgentRunEventRecorder,
        tool_runtime,
        capability_resolver,
        context_builder,
        evaluator,
        *,
        interface_manager,
        behaviors,
        managed_permission_manager,
        audit_service,
        clock=None,
    ) -> None:
        self.lifecycle = lifecycle
        self.registry = registry
        self.runs = runs
        self.checkpoints = checkpoints
        self.events = events
        self.tool_runtime = tool_runtime
        self.capability_resolver = capability_resolver
        self.context_builder = context_builder
        self.evaluator = evaluator
        self.interface_manager = interface_manager
        self.behaviors = behaviors
        self.managed_permission_manager = managed_permission_manager
        self.audit_service = audit_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- public entry point ---------------------------------------------------

    async def execute(self, run_id: str) -> AgentRun:
        run = self.lifecycle.get_run(run_id)
        task = self.lifecycle.get_task(run.task_id)
        definition = self.registry.get_enabled(run.agent_id, run.agent_version)
        behavior = self.behaviors.get((run.agent_id, run.agent_version))
        if behavior is None:
            raise AgentControllerError(
                "No trusted behavior is registered for this agent version."
            )

        if run.status is AgentRunStatus.RUNNING and self.lifecycle.has_executor(run_id):
            raise AgentConcurrencyError("Another executor already holds this run.")
        if run.status is AgentRunStatus.PENDING:
            run = self.lifecycle.start(run_id, expected_version=run.version)
        elif run.status is AgentRunStatus.PAUSED:
            if run.pending_approval_id:
                raise AgentControllerError(
                    "The run still has an unresolved approval; decide it first."
                )
            run = self.lifecycle.resume(run_id, expected_version=run.version)
        elif run.status is not AgentRunStatus.RUNNING:
            raise AgentControllerError("The run is already finished.")

        # The run is now RUNNING and executor-claimed: every later failure path
        # must release the executor claim and leave a truthful terminal state.
        try:
            binding = self.capability_resolver.resolve(definition, run, task)
            # Exact per-run knowledge grants are issued once, on the first attempt,
            # by trusted application code; agent subjects can never issue grants.
            if run.attempt <= 1:
                issued = self.capability_resolver.issue_capability_grants(
                    definition, run, task, binding,
                    issuer=PermissionSubject(SubjectType.USER, "local-user"),
                    managed=self.managed_permission_manager,
                    audit_service=self.audit_service,
                )
                if issued:
                    self.events.record(
                        run_id=run_id,
                        event_type="capability_grants_issued",
                        outcome="issued",
                        metadata={"count": issued, "agent_id": run.agent_id},
                    )
            ctx = self.context_builder.build(definition, run, task, binding=binding)
        except AgentConcurrencyError:
            # Claim conflicts during start/resume release their own claim.
            raise
        except Exception:
            self._release_and_fail(
                run_id,
                error_code="context_or_capability_error",
                error_message=(
                    "Execution stopped before the first step: context or "
                    "capability validation failed."
                ),
            )
            raise

        observations, pending = self._restore_state(run_id)
        started = time.monotonic()
        try:
            while True:
                run = self.runs.get(run_id)
                if run is None:
                    raise AgentControllerError("The run disappeared during execution.")
                if run.status is not AgentRunStatus.RUNNING:
                    # An external cancel or pause took effect between steps.
                    return run

                iteration = run.iteration + 1
                self._enforce_time_and_iterations(definition.budgets, iteration, started)
                run = self._advance(run_id, run.version, iteration=iteration)

                if pending is not None:
                    decision = pending
                    retry_approval = True
                    pending = None
                else:
                    try:
                        decision = behavior.decide(ctx, {
                            "observations": list(observations),
                            "iteration": iteration,
                        })
                    except Exception as exc:
                        return self._fail(
                            run_id,
                            error_code="behavior_error",
                            error_message=str(exc)[:300],
                            stop_reason=StopReason.FAILED,
                        )
                    retry_approval = False

                kind = decision.get("kind")
                if kind == "tool":
                    run, observations = await self._act_on_tool(
                        run, ctx, observations, decision, retry_approval,
                    )
                    if run.status is not AgentRunStatus.RUNNING:
                        return run
                elif kind == "model":
                    run, observations = await self._act_on_model(
                        definition, run, task, observations, decision,
                    )
                elif kind == "finish":
                    outcome = dict(decision.get("outcome") or {})
                    if decision.get("status") == "failed" and isinstance(decision.get("error_code"), str):
                        return self._fail(
                            run_id,
                            error_code=str(decision["error_code"]),
                            error_message=str(decision.get("error_message", ""))[:300],
                            stop_reason=StopReason.FAILED,
                        )
                    return self._complete(run_id, definition, outcome)
                else:
                    return self._fail(
                        run_id,
                        error_code="invalid_behavior_decision",
                        error_message="The trusted behavior produced an unsupported decision kind.",
                        stop_reason=StopReason.FAILED,
                    )
        except AgentConcurrencyError:
            run = self.runs.get(run_id)
            # The loop already claimed the executor: a concurrent owner's
            # transition must not leak our claim.
            self.lifecycle.release_executor(run_id)
            if run is not None and run.status is not AgentRunStatus.RUNNING:
                return run
            raise
        except AgentBudgetExceededError as exc:
            return self._fail(
                run_id,
                error_code="budget_exceeded",
                error_message=str(exc)[:300],
                stop_reason=exc.stop_reason,
            )
        except Exception:
            self._release_and_fail(
                run_id,
                error_code="execution_error",
                error_message="The run failed unexpectedly; inspect the redacted events.",
            )
            raise

    # -- tool actions -----------------------------------------------------------

    async def _act_on_tool(self, run, ctx, observations, decision, retry_approval):
        tool_id = decision.get("tool_id")
        input_data = decision.get("input")
        if not isinstance(tool_id, str) or not isinstance(input_data, dict):
            return self._fail(
                run.run_id,
                error_code="invalid_tool_proposal",
                error_message="The behavior proposed a malformed tool call.",
                stop_reason=StopReason.FAILED,
            ), observations

        capability = ctx.binding.capability_for(tool_id)
        if capability is None:
            return self._fail(
                run.run_id,
                error_code="capability_not_bound",
                error_message="The proposed tool is not bound to this run.",
                stop_reason=StopReason.PERMISSION_DENIED,
            ), observations
        if capability.resource_type is not ResourceType.KNOWLEDGE_SOURCE or capability.operation.value != "read":
            return self._fail(
                run.run_id,
                error_code="unsupported_capability_binding",
                error_message="Phase 6 supports only bound knowledge read capabilities.",
                stop_reason=StopReason.PERMISSION_DENIED,
            ), observations

        scope_id = str(input_data.get("scope_id", ""))
        scope_type = str(input_data.get("scope_type", ""))
        scope_owner = str(input_data.get("owner_id", ""))
        declared = (scope_type, scope_id, scope_owner)
        scope_match = any(
            (scope.scope_type, scope.scope_id, scope.owner_id) == declared
            for scope in ctx.binding.knowledge_scopes
        )
        if not declared[0] or not declared[1] or not declared[2] or not scope_match:
            return self._fail(
                run.run_id,
                error_code="scope_not_bound",
                error_message="The proposal targets a scope that was not bound to this run.",
                stop_reason=StopReason.PERMISSION_DENIED,
            ), observations
        if input_data.get("run_id") != run.run_id:
            return self._fail(
                run.run_id,
                error_code="run_identity_mismatch",
                error_message="The proposal declared a different run identity.",
                stop_reason=StopReason.PERMISSION_DENIED,
            ), observations
        self._enforce_tool_calls(run.run_id, ctx, run.tool_calls)

        run = self._advance(run.run_id, run.version, tool_calls=run.tool_calls + 1)
        access = self._build_access_request(run, capability, scope_type, scope_id, scope_owner, decision)
        request = ToolCallRequest(
            tool_id=tool_id,
            version=capability.version,
            access_request=access,
            input_data=input_data,
            approval_id=decision.get("approval_id") if retry_approval else None,
        )
        result = await self.tool_runtime.execute(request)

        if result.ok:
            observation = {
                "kind": "tool", "ok": True, "tool_id": tool_id,
                "output": self._bound_output(result.output),
                "count": self._result_count(result.output),
            }
            observations = self._acknowledge(run, observations, observation)
            return run, observations

        category = result.error_category or "unknown"
        if category == "approval_required" and not retry_approval:
            run = await self._pause_for_approval(run, decision, request)
            if run.status is AgentRunStatus.RUNNING:
                return run, observations
            return run, observations
        observation = {
            "kind": "tool", "ok": False, "tool_id": tool_id,
            "error_category": category,
        }
        observations = self._acknowledge(run, observations, observation)
        return run, observations

    async def _pause_for_approval(self, run, decision, request) -> AgentRun:
        try:
            approval = self.tool_runtime.request_approval(
                request, requested_by=run.owner_id,
            )
        except Exception as exc:
            return self._fail(
                run.run_id,
                error_code="approval_request_failed",
                error_message=str(exc)[:300],
                stop_reason=StopReason.FAILED,
            )
        pending = {
            "kind": "tool",
            "tool_id": decision.get("tool_id"),
            "input": dict(decision.get("input") or {}),
            "access": {"request_id": request.access_request.request_id},
            "approval_id": approval.approval_id,
        }
        payload = {
            "schema": "agent.checkpoint/1",
            "observations": list(self._restore_observations(run.run_id)),
            "pending": pending,
        }
        run = self._checkpoint(run, payload)
        self.events.record(
            run_id=run.run_id,
            event_type="approval_requested",
            outcome="pending",
            metadata={"approval_id": approval.approval_id, "tool_id": decision.get("tool_id")},
        )
        return self.lifecycle.pause_for_approval(
            run.run_id, expected_version=run.version, approval_id=approval.approval_id,
        )

    # -- model actions ----------------------------------------------------------

    async def _act_on_model(self, definition, run, task, observations, decision):
        provider_id = str(decision.get("provider_id", ""))
        model_id = str(decision.get("model_id", ""))
        route = provider_id + "/" + model_id
        allowed = route in definition.allowed_models
        authorized = task.payload.get("allow_model_transmission") is True
        if not allowed:
            observation = {
                "kind": "model", "ok": False,
                "reason_code": "model_not_allowed",
                "provider_id": provider_id, "model_id": model_id,
            }
            observations = self._acknowledge(run, observations, observation)
            return run, observations
        if not authorized:
            # Private local context must never reach a provider without explicit
            # task-level authorization recorded in the payload.
            observation = {
                "kind": "model", "ok": False,
                "reason_code": "transmission_not_authorized",
                "provider_id": provider_id, "model_id": model_id,
            }
            observations = self._acknowledge(run, observations, observation)
            return run, observations

        estimated = int(decision.get("estimated_prompt_tokens", 0) or 0)
        if run.model_tokens + estimated > definition.budgets.max_model_tokens:
            raise AgentBudgetExceededError(
                StopReason.TOKEN_BUDGET_EXHAUSTED,
                "The model token budget would be exceeded by this call.",
            )

        prompt = str(decision.get("prompt", ""))[:2000]
        messages = [
            {"role": "system", "content": ctx_goal_text(definition.goal)},
            {"role": "user", "content": prompt},
        ]
        response_text = ""
        try:
            async for chunk in self.interface_manager.stream_chat(
                provider_id, messages, model=model_id,
            ):
                text = str(chunk)
                response_text += text
                estimated += len(text.split())
                if estimated > definition.budgets.max_model_tokens:
                    break
        except Exception as exc:
            observation = {
                "kind": "model", "ok": False,
                "reason_code": getattr(exc, "category", "model_unavailable"),
                "provider_id": provider_id, "model_id": model_id,
            }
            observations = self._acknowledge(run, observations, observation)
            return run, observations
        run = self._advance(run.run_id, run.version, model_tokens=estimated)
        observation = {
            "kind": "model", "ok": True,
            "provider_id": provider_id, "model_id": model_id,
            "text": response_text,
            "truncated": estimated > definition.budgets.max_model_tokens,
        }
        observations = self._acknowledge(run, observations, observation)
        return run, observations

    # -- terminal actions ---------------------------------------------------------

    def _complete(self, run_id, definition: AgentDefinition, outcome) -> AgentRun:
        try:
            annotated = self.evaluator.evaluate(definition, outcome)
        except Exception as exc:
            return self._fail(
                run_id,
                error_code="evaluation_failed",
                error_message=str(exc)[:300],
                stop_reason=StopReason.FAILED,
            )
        final = dict(outcome)
        final["completion"] = {
            "status": annotated.status,
            "criteria_met": annotated.criteria_met,
            "reason": annotated.reason,
        }
        if _json_bytes(final) > definition.budgets.max_output_bytes:
            return self._fail(
                run_id,
                error_code="outcome_too_large",
                error_message="The run outcome exceeds the declared output budget.",
                stop_reason=StopReason.OUTPUT_LIMIT,
            )
        run = self.runs.get(run_id)
        if run is None:
            raise AgentControllerError("The run disappeared during completion.")
        run = self._checkpoint(run, {
            "schema": "agent.checkpoint/1",
            "observations": [],
            "outcome": final,
        })
        return self.lifecycle.complete(run_id, expected_version=run.version, outcome=final)

    def _fail(self, run_id, *, error_code, error_message, stop_reason) -> AgentRun:
        run = self.runs.get(run_id)
        if run is None:
            raise AgentControllerError("The run disappeared during failure handling.")
        return self.lifecycle.fail(
            run_id, expected_version=run.version,
            error_code=error_code,
            error_message=error_message,
            stop_reason=stop_reason,
        )

    def _release_and_fail(self, run_id: str, *, error_code: str, error_message: str) -> None:
        """Release the executor claim and fail the run after an unexpected error.

        No failure path may leave a run RUNNING or an executor claim leaked.
        The message is static and redacted: raw exception details are never
        persisted into run state or events.
        """
        self.lifecycle.release_executor(run_id)
        try:
            self._fail(
                run_id,
                error_code=error_code,
                error_message=error_message,
                stop_reason=StopReason.FAILED,
            )
        except Exception:
            # _fail can itself fail (run vanished, concurrent terminal state);
            # never mask the original exception.
            pass

    # -- state helpers ------------------------------------------------------------

    def _advance(self, run_id, expected_version, **updates) -> AgentRun:
        updated = self.runs.transition(run_id, expected_version=expected_version, **updates)
        if updated is None:
            raise AgentControllerError("The run disappeared during execution.")
        return updated

    def _acknowledge(self, run, observations, observation: dict):
        bounded = _bounded_observation(observation)
        observations = (list(observations) + [bounded])[-9:]
        run = self._checkpoint(run, {
            "schema": "agent.checkpoint/1",
            "observations": observations,
            "pending": None,
        })
        metadata = {
            "iteration": run.iteration,
            "tool_calls": run.tool_calls,
            "kind": bounded.get("kind"),
            "outcome": "succeeded" if bounded.get("ok") else "failed",
        }
        if bounded.get("error_category"):
            metadata["reason_code"] = bounded["error_category"]
        self.events.record(
            run_id=run.run_id,
            event_type="step_observed",
            outcome=metadata["outcome"],
            metadata=metadata,
        )
        return observations

    def _checkpoint(self, run, payload) -> AgentRun:
        sequence = run.last_checkpoint_sequence + 1
        checkpoint = AgentCheckpoint(
            checkpoint_id=uuid4().hex,
            run_id=run.run_id,
            sequence=sequence,
            schema_version=1,
            payload=payload,
            created_at=self._clock(),
        )
        self.checkpoints.append(checkpoint)
        return self._advance(
            run.run_id, run.version, last_checkpoint_sequence=sequence,
        )

    def _enforce_time_and_iterations(self, budgets: AgentBudgets, iteration: int, started: float) -> None:
        if time.monotonic() - started > budgets.deadline_seconds:
            raise AgentBudgetExceededError(
                StopReason.DEADLINE_EXCEEDED,
                "The run exceeded its wall-clock deadline.",
            )
        if iteration > budgets.max_iterations:
            raise AgentBudgetExceededError(
                StopReason.MAX_ITERATIONS,
                "The run exceeded its maximum iteration budget.",
            )

    def _enforce_tool_calls(self, run_id, ctx, tool_calls: int) -> None:
        # Tool-call budget is enforced inside the resolve path from the definition.
        budgets = self.registry.get(ctx.agent_id, ctx.agent_version).budgets
        if tool_calls + 1 > budgets.max_tool_calls:
            raise AgentBudgetExceededError(
                StopReason.TOOL_CALL_LIMIT,
                "The run reached its tool-call limit.",
            )

    def _restore_state(self, run_id: str):
        latest = self.checkpoints.latest(run_id)
        if latest is None:
            return [], None
        payload = latest.payload or {}
        observations = payload.get("observations")
        if not isinstance(observations, list):
            observations = []
        pending = payload.get("pending") if isinstance(payload.get("pending"), dict) else None
        return observations, pending

    def _restore_observations(self, run_id: str):
        observations, _pending = self._restore_state(run_id)
        return observations

    def _build_access_request(
        self, run, capability, scope_type: str, scope_id: str, scope_owner: str, decision,
    ) -> AccessRequest:
        stored = decision.get("access") if isinstance(decision.get("access"), dict) else {}
        stored_request_id = str(stored.get("request_id") or "")
        kwargs = {"request_id": stored_request_id} if stored_request_id else {}
        return AccessRequest(
            subject=PermissionSubject(SubjectType.AGENT_RUN, run.run_id),
            resource=PermissionResource(capability.resource_type, scope_id),
            operation=capability.operation,
            scope=PermissionScope(ScopeType(scope_type), scope_id, scope_owner),
            **kwargs,
        )

    @staticmethod
    def _bound_output(output, maximum: int = 2048):
        if isinstance(output, dict):
            bounded = {}
            for key, value in list(output.items()):
                if isinstance(value, (list, dict)):
                    bounded[key] = value
                else:
                    bounded[key] = str(value)[:128]
            if _json_bytes(bounded) > maximum:
                results = bounded.get("results")
                if isinstance(results, list):
                    bounded["results"] = results[:5]
                    bounded["truncated"] = True
            return bounded
        return str(output)[:256]

    @staticmethod
    def _result_count(output) -> int:
        if isinstance(output, dict) and isinstance(output.get("results"), list):
            return len(output["results"])
        return 0


def ctx_goal_text(goal: str) -> str:
    return "Agent goal: " + goal

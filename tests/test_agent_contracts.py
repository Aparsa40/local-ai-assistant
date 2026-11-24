"""WP-6.1 / WP-6.7 regression tests for the Agent Runtime typed contracts."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.agents.contracts import (
    MAX_CHECKPOINT_BYTES,
    AgentBudgets,
    AgentCheckpoint,
    AgentDefinition,
    AgentDefinitionError,
    AgentRun,
    AgentRunStatus,
    AgentTask,
    AgentTransitionError,
    CompletionCriteria,
    DataScope,
    RunEvent,
    StopReason,
    TaskStatus,
    can_transition,
    new_run_id,
    new_task_id,
    require_transition,
)


def make_definition(**overrides) -> AgentDefinition:
    values = dict(
        agent_id="contract-agent",
        version="1.0.0",
        goal="A valid bounded goal.",
        description="A valid bounded description.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        completion=CompletionCriteria(
            kind="sources_collected",
            description="One source collected.",
        ),
    )
    values.update(overrides)
    return AgentDefinition(**values)


def now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestDataScope:
    def test_accepts_valid_declared_domain(self):
        scope = DataScope("knowledge", "user", "scope-1", "local-user")
        assert scope.domain == "knowledge"

    @pytest.mark.parametrize("domain", ["", "files", "all", "KNOWLEDGE"])
    def test_rejects_undeclared_domains(self, domain):
        with pytest.raises(AgentDefinitionError):
            DataScope(domain, "user", "scope-1", "local-user")

    def test_rejects_blank_identifiers(self):
        with pytest.raises(ValueError):
            DataScope("knowledge", "user", "", "local-user")
        with pytest.raises(ValueError):
            DataScope("knowledge", "user", "scope-1", "")

    def test_rejects_wildcard_identifiers(self):
        with pytest.raises(ValueError):
            DataScope("knowledge", "user", "*", "local-user")
        with pytest.raises(ValueError):
            DataScope("knowledge", "user", "scope-1", "any")


class TestAgentTask:
    def test_accepts_owner_owned_scopes(self):
        task = AgentTask(
            task_id=new_task_id(),
            agent_id="contract-agent",
            agent_version="1.0.0",
            owner_id="local-user",
            title="Analyze scope",
            payload={"query": "durable"},
            data_scopes=(DataScope("knowledge", "user", "scope-1", "local-user"),),
        )
        assert task.status is TaskStatus.OPEN

    def test_rejects_scopes_owned_by_someone_else(self):
        with pytest.raises(ValueError, match="task owner"):
            AgentTask(
                task_id=new_task_id(),
                agent_id="contract-agent",
                agent_version="1.0.0",
                owner_id="local-user",
                title="Analyze scope",
                payload={},
                data_scopes=(DataScope("knowledge", "user", "scope-1", "other-owner"),),
            )

    def test_rejects_malformed_ids_and_titles(self):
        with pytest.raises(ValueError):
            AgentTask(
                task_id="not-hex",
                agent_id="contract-agent",
                agent_version="1.0.0",
                owner_id="local-user",
                title="Analyze scope",
                payload={},
            )
        with pytest.raises(ValueError):
            AgentTask(
                task_id=new_task_id(),
                agent_id="contract-agent",
                agent_version="1.0.0",
                owner_id="local-user",
                title=" ",
                payload={},
            )


class TestAgentRun:
    def make_run(self, **overrides):
        values = dict(
            run_id=new_run_id(),
            task_id=new_task_id(),
            agent_id="contract-agent",
            agent_version="1.0.0",
            owner_id="local-user",
            trace_id=new_run_id(),
            status=AgentRunStatus.PENDING,
            scope_type="task",
            scope_id=new_task_id(),
        )
        values.update(overrides)
        return AgentRun(**values)

    def test_defaults_are_bounded(self):
        run = self.make_run()
        assert run.version == 1
        assert run.attempt == 1
        assert run.iteration == 0
        assert run.tool_calls == 0
        assert run.model_tokens == 0
        assert run.stop_reason is None
        assert run.outcome is None

    def test_rejects_malformed_identity(self):
        with pytest.raises(ValueError):
            self.make_run(run_id="ZZZZ")
        with pytest.raises(ValueError):
            self.make_run(status="running")

    def test_rejects_negative_counters(self):
        with pytest.raises(ValueError):
            self.make_run(iteration=-1)
        with pytest.raises(ValueError):
            self.make_run(model_tokens=-5)

    def test_rejects_malformed_optional_fields(self):
        with pytest.raises(ValueError):
            self.make_run(stop_reason="completed")
        with pytest.raises(ValueError):
            self.make_run(error_message="x" * 301)
        with pytest.raises(ValueError):
            self.make_run(created_at=datetime(2026, 1, 1))  # naive datetime

    def test_rejects_oversized_outcome(self):
        with pytest.raises(ValueError):
            self.make_run(outcome={"blob": "x" * (256 * 1024)})


class TestAgentBudgets:
    @pytest.mark.parametrize(
        "field, value",
        [
            ("max_iterations", 0),
            ("max_iterations", 1001),
            ("deadline_seconds", 0),
            ("deadline_seconds", 3601),
            ("max_tool_calls", -1),
            ("max_input_bytes", 0),
            ("max_output_bytes", 2 * 1024 * 1024),
            ("max_model_tokens", -1),
            ("max_model_tokens", 2000000),
        ],
    )
    def test_rejects_out_of_range_values(self, field, value):
        with pytest.raises(AgentDefinitionError):
            AgentBudgets(**{field: value})

    def test_zero_model_tokens_is_allowed(self):
        budgets = AgentBudgets(max_model_tokens=0)
        assert budgets.max_model_tokens == 0


class TestAgentDefinitionValidation:
    def test_accepts_the_builtin_shape(self):
        definition = make_definition()
        assert definition.approval_policy == "explicit"
        assert definition.enabled is True

    @pytest.mark.parametrize(
        "field, value",
        [
            ("agent_id", "Not-Valid"),
            ("agent_id", "x"),  # the pattern requires at least two characters
            ("version", "1.0"),
            ("goal", ""),
            ("goal", 42),
        ],
    )
    def test_rejects_invalid_identity_fields(self, field, value):
        with pytest.raises((AgentDefinitionError, ValueError)):
            make_definition(**{field: value})

    def test_rejects_unsupported_schema_keywords(self):
        with pytest.raises(AgentDefinitionError, match="unsupported schema keywords"):
            make_definition(input_schema={"type": "object", "$ref": "#/definitions/x"})

    def test_rejects_schemas_without_a_declared_type(self):
        with pytest.raises(AgentDefinitionError, match="must declare a supported type"):
            make_definition(input_schema={"properties": {}})

    def test_rejects_overly_nested_schemas(self):
        nested = {"type": "object"}
        for _ in range(12):
            nested = {"type": "object", "properties": {"leaf": nested}}
        with pytest.raises(AgentDefinitionError, match="nesting exceeds depth"):
            make_definition(input_schema=nested)

    def test_rejects_non_explicit_approval_policies(self):
        with pytest.raises(AgentDefinitionError, match="explicit"):
            make_definition(approval_policy="auto")

    def test_rejects_unsupported_completion_kinds(self):
        with pytest.raises(AgentDefinitionError, match="completion kind"):
            make_definition(
                completion=CompletionCriteria(kind="self_assessed", description="Invalid kind.")
            )

    def test_rejects_tool_and_model_overruns(self):
        with pytest.raises(AgentDefinitionError, match="allowed_tools"):
            make_definition(allowed_tools=("Bad-Tool",))
        with pytest.raises(AgentDefinitionError, match="allowed_models"):
            make_definition(allowed_models=tuple(f"m{i}" for i in range(51)))

    def test_rejects_undeclared_data_domains(self):
        with pytest.raises(AgentDefinitionError, match="data domain"):
            make_definition(data_scopes=("filesystem",))


def TRANSITIONS_IS_EMPTY(status):
    from core.agents.contracts import TRANSITIONS

    return len(TRANSITIONS[status]) == 0


def TRANSITIONS_FOR_PAUSE():
    from core.agents.contracts import TRANSITIONS

    return TRANSITIONS[AgentRunStatus.PAUSED]


class TestTransitions:
    def test_pending_can_start_or_cancel_only(self):
        assert can_transition(AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
        assert can_transition(AgentRunStatus.PENDING, AgentRunStatus.CANCELLED)
        assert not can_transition(AgentRunStatus.PENDING, AgentRunStatus.PAUSED)
        assert not can_transition(AgentRunStatus.PENDING, AgentRunStatus.SUCCEEDED)

    def test_running_can_not_restart(self):
        assert not can_transition(AgentRunStatus.RUNNING, AgentRunStatus.RUNNING)

    def test_terminal_states_are_absorbing(self):
        for terminal in (
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        ):
            assert TRANSITIONS_IS_EMPTY(terminal)

    def test_paused_can_only_resume_or_cancel(self):
        target = TRANSITIONS_FOR_PAUSE()
        assert AgentRunStatus.RUNNING in target
        assert AgentRunStatus.CANCELLED in target
        assert AgentRunStatus.SUCCEEDED not in target

    def test_require_transition_raises_for_illegal_transition(self):
        with pytest.raises(AgentTransitionError):
            require_transition(AgentRunStatus.SUCCEEDED, AgentRunStatus.RUNNING)

    def test_transition_helpers_reject_non_enum_values(self):
        with pytest.raises(ValueError):
            can_transition("running", AgentRunStatus.PAUSED)


class TestCheckpointsAndEvents:
    def test_checkpoint_requires_version_one_schema(self):
        with pytest.raises(ValueError):
            AgentCheckpoint(
                checkpoint_id=new_run_id(),
                run_id=new_run_id(),
                sequence=1,
                schema_version=2,
                payload={"schema": "agent.checkpoint/2"},
            )

    def test_checkpoint_payload_is_bounded(self):
        with pytest.raises(ValueError):
            AgentCheckpoint(
                checkpoint_id=new_run_id(),
                run_id=new_run_id(),
                sequence=1,
                schema_version=1,
                payload={"blob": "x" * (MAX_CHECKPOINT_BYTES + 1)},
            )

    def test_run_event_validation(self):
        run_id = new_run_id()
        event = RunEvent(
            event_id=new_run_id(),
            run_id=run_id,
            event_type="run_started",
            ordinal=1,
            outcome="running",
            metadata={"agent_id": "contract-agent"},
            created_at=now(),
        )
        assert event.event_type == "run_started"
        with pytest.raises(ValueError):
            RunEvent(
                event_id=new_run_id(),
                run_id="short",
                event_type="run_started",
                ordinal=1,
                outcome="running",
            )
        with pytest.raises(ValueError):
            RunEvent(
                event_id=new_run_id(),
                run_id=run_id,
                event_type="run_started",
                ordinal=1,
                outcome="x" * 41,
            )
        with pytest.raises(ValueError):
            RunEvent(
                event_id=new_run_id(),
                run_id=run_id,
                event_type="run_started",
                ordinal=1,
                outcome="running",
                metadata={"blob": "x" * (4096 + 1)},
            )

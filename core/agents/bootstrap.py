"""Application-side composition root for the bounded Agent Runtime.

The container owns the single trusted AgentRegistry activation path and the
application ToolRegistry instance used by agents. It builds per-session service
sets from the existing permission, storage, and tool runtime components; it
never creates parallel persistence, provider, or permission systems.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.agents.builtins import AGENT_ID, AGENT_VERSION, KnowledgeAnalysisAgent
from core.agents.controller import ExecutionController
from core.agents.context import AgentContextBuilder, CapabilityResolver
from core.agents.evaluator import CompletionEvaluator
from core.agents.events import AgentRunEventRecorder
from core.agents.lifecycle import AgentLifecycleManager
from core.agents.registry import AgentRegistry
from core.knowledge import KnowledgeScope, KnowledgeService
from core.permissions.approvals import ApprovalService
from core.permissions.audit import AuditService
from core.permissions.knowledge_adapter import PermissionManagerKnowledgeAccessPolicy
from core.permissions.local_policy import LocalApplicationPolicy
from core.permissions.manager import PermissionManager
from core.permissions.owner_policies import LocalOwnerApprovalDecisionPolicy, LocalOwnerGrantAdministrationPolicy
from core.permissions.types import (
    PermissionOperation,
    PermissionSubject,
    ResourceType,
    SubjectType,
)
from core.repositories.agent_repository import AgentDefinitionRepository
from core.repositories.approval_repository import ApprovalRepository
from core.repositories.audit_repository import AuditRepository
from core.repositories.permission_repository import PermissionRepository
from core.repositories.run_repository import (
    AgentCheckpointRepository,
    AgentRunEventRepository,
    AgentRunRepository,
)
from core.repositories.task_repository import AgentTaskRepository
from core.tools.registry import ToolRegistry
from core.tools.runtime import ToolRuntime
from core.tools.schemas import ToolDefinition, ToolRiskClass

KNOWLEDGE_SEARCH_TOOL_ID = "knowledge_search"
KNOWLEDGE_SEARCH_VERSION = "1.0.0"


def _knowledge_search_definition() -> ToolDefinition:
    return ToolDefinition(
        tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
        version=KNOWLEDGE_SEARCH_VERSION,
        description="Search one explicitly bound knowledge scope; read-only.",
        resource_type=ResourceType.KNOWLEDGE_SOURCE,
        operation=PermissionOperation.READ,
        risk_class=ToolRiskClass.READ_ONLY,
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "minLength": 32, "maxLength": 32},
                "scope_type": {
                    "type": "string",
                    "enum": ["user", "conversation", "task", "global"],
                    "minLength": 1,
                    "maxLength": 40,
                },
                "scope_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "owner_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["run_id", "scope_type", "scope_id", "owner_id", "query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 0, "maximum": 10},
                "truncated": {"type": "boolean"},
                "results": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string", "maxLength": 160},
                            "chunk_id": {"type": "integer", "minimum": 0},
                            "title": {"type": "string", "maxLength": 200},
                            "source_type": {"type": "string", "maxLength": 40},
                            "uri": {"type": "string", "maxLength": 400},
                            "rank": {"type": "number"},
                            "content": {"type": "string", "maxLength": 400},
                        },
                        "required": [
                            "source_id", "chunk_id", "title", "source_type",
                            "uri", "rank", "content",
                        ],
                    },
                },
            },
            "required": ["count", "truncated", "results"],
        },
        timeout_seconds=15,
        max_input_bytes=16384,
        max_output_bytes=32768,
    )


def _knowledge_search_handler(storage_session_factory):
    """Return a read-only handler bound to one owned storage factory.

    The handler is authorized twice: centrally by ToolRuntime plus
    PermissionManager against the exact per-run grant, and at service level by
    KnowledgeService through the same run subject. It never receives sessions
    from agent code and truncates all returned content.
    """
    async def handler(input_data: dict) -> dict:
        run_id = str(input_data.get("run_id", ""))
        scope_type = str(input_data.get("scope_type", ""))
        scope_id = str(input_data.get("scope_id", ""))
        owner_id = str(input_data.get("owner_id", ""))
        query = str(input_data.get("query", ""))
        limit = input_data.get("limit", 5)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            limit = 5
        with storage_session_factory() as db:
            audit = AuditService(AuditRepository(db))
            permission_manager = PermissionManager(
                PermissionRepository(db),
                policies=(LocalApplicationPolicy(),),
            )
            policy = PermissionManagerKnowledgeAccessPolicy(
                permission_manager,
                PermissionSubject(SubjectType.AGENT_RUN, run_id),
                audit_service=audit,
            )
            service = KnowledgeService(db, access_policy=policy)
            results = service.search(
                KnowledgeScope(scope_type, scope_id, owner_id),
                query,
                limit=limit,
            )
        bounded = [
            {
                "source_id": str(row.source_id),
                "chunk_id": int(row.chunk_id),
                "title": str(row.title or "")[:200],
                "source_type": str(row.source_type or ""),
                "uri": str(row.uri or "")[:400],
                "rank": float(row.rank),
                "content": str(row.content or "")[:400],
            }
            for row in results
        ]
        return {
            "count": len(bounded),
            "truncated": len(results) >= limit,
            "results": bounded,
        }

    return handler


@dataclass(frozen=True, slots=True)
class AgentServices:
    """One request-scoped set of Agent Runtime services over a single session."""

    db: object
    registry: AgentRegistry
    lifecycle: AgentLifecycleManager
    controller: ExecutionController
    tasks: AgentTaskRepository
    runs: AgentRunRepository
    checkpoints: AgentCheckpointRepository
    events: AgentRunEventRecorder
    permission_manager: PermissionManager
    audit_service: AuditService
    tool_runtime: ToolRuntime


class AgentRuntimeContainer:
    """Builds trusted registry activation and per-session agent services."""

    def __init__(self, storage_manager, interface_manager, *, tool_registry=None) -> None:
        self._storage_manager = storage_manager
        self.interface_manager = interface_manager
        self.tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self.behaviors: dict = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        known = {
            str(entry["tool_id"]) + ":" + str(entry["version"])
            for entry in self.tool_registry.public_catalog()
        }
        key = KNOWLEDGE_SEARCH_TOOL_ID + ":" + KNOWLEDGE_SEARCH_VERSION
        if key not in known:
            self.tool_registry.register(
                _knowledge_search_definition(),
                _knowledge_search_handler(self._storage_manager.session),
            )

    def register_builtin_agents(self, db) -> None:
        """Persist the builtin definition and activate its trusted behavior."""
        repository = AgentDefinitionRepository(db)
        try:
            repository.register(KnowledgeAnalysisAgent.definition())
        except Exception:
            # Startup registration is idempotent: an already persisted builtin
            # definition is accepted, anything else fails loudly.
            db.rollback()
            if repository.get(AGENT_ID, AGENT_VERSION) is None:
                raise
        self.behaviors[(AGENT_ID, AGENT_VERSION)] = KnowledgeAnalysisAgent()

    def build_services(self, db) -> AgentServices:
        audit = AuditService(AuditRepository(db))
        # The trusted local owner issues the exact per-run capability grants;
        # all other grant administration stays denied by default.
        permission_manager = PermissionManager(
            PermissionRepository(db),
            grant_policy=LocalOwnerGrantAdministrationPolicy(),
            policies=(LocalApplicationPolicy(),),
        )
        approval_service = ApprovalService(
            ApprovalRepository(db),
            audit,
            decision_policy=LocalOwnerApprovalDecisionPolicy(),
        )
        tool_runtime = ToolRuntime(
            self.tool_registry,
            permission_manager,
            audit,
            approval_service=approval_service,
        )
        tasks = AgentTaskRepository(db)
        runs = AgentRunRepository(db)
        checkpoints = AgentCheckpointRepository(db)
        events = AgentRunEventRecorder(AgentRunEventRepository(db))
        registry = AgentRegistry(AgentDefinitionRepository(db))
        lifecycle = AgentLifecycleManager(registry, tasks, runs, events)
        context_builder = AgentContextBuilder(permission_manager, audit_service=audit)
        capability_resolver = CapabilityResolver(self.tool_registry)
        controller = ExecutionController(
            lifecycle,
            registry,
            runs,
            checkpoints,
            events,
            tool_runtime,
            capability_resolver,
            context_builder,
            CompletionEvaluator(),
            interface_manager=self.interface_manager,
            behaviors=self.behaviors,
            managed_permission_manager=permission_manager,
            audit_service=audit,
        )
        return AgentServices(
            db=db,
            registry=registry,
            lifecycle=lifecycle,
            controller=controller,
            tasks=tasks,
            runs=runs,
            checkpoints=checkpoints,
            events=events,
            permission_manager=permission_manager,
            audit_service=audit,
            tool_runtime=tool_runtime,
        )

    def recover_stale_runs(self) -> int:
        """Pause runs left RUNNING by an interrupted previous process."""
        with self._storage_manager.session() as db:
            services = self.build_services(db)
            return services.lifecycle.recover_stale_runs()

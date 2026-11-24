"""Assemble explicit, bounded, provenance-aware request context."""

from __future__ import annotations

from core.conversations.service import ConversationService
from core.memory.service import MemoryService
from core.memory.types import MemoryScope

from .ranking import conversation_recency_score, presentation_key, selection_key
from .schemas import ContextItem, ContextPackage, ContextRequest
from .token_budget import TokenBudgetPolicy


class ContextManagerError(Exception):
    """Base class for expected context assembly failures."""


class ContextValidationError(ContextManagerError, ValueError):
    """The request or its limits are invalid."""


class ContextConfigurationError(ContextManagerError):
    """A requested context source has not been configured."""


class ContextManager:
    """Builds one request package without direct ORM or storage access."""

    MAX_QUERY_LENGTH = 12000
    MAX_HISTORY_LIMIT = 100
    MAX_MEMORY_LIMIT = 50
    MAX_MEMORY_SCOPES = 10
    MAX_TOKEN_BUDGET = 32000

    def __init__(
        self,
        conversations: ConversationService,
        memory: MemoryService | None = None,
        token_budget: TokenBudgetPolicy | None = None,
    ) -> None:
        self.conversations = conversations
        self.memory = memory
        self.token_budget = token_budget or TokenBudgetPolicy()

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    @classmethod
    def _validate_request(cls, request: ContextRequest) -> None:
        if isinstance(request.conversation_id, bool) or not isinstance(request.conversation_id, int) or request.conversation_id < 1:
            raise ContextValidationError("شناسه گفتگو معتبر نیست")
        if not isinstance(request.query, str) or not request.query.strip() or len(request.query) > cls.MAX_QUERY_LENGTH:
            raise ContextValidationError("متن درخواست خالی یا بیش از حد مجاز است")
        if not isinstance(request.owner_id, str) or not request.owner_id.strip() or len(request.owner_id) > 160:
            raise ContextValidationError("شناسه مالک معتبر نیست")
        for value, minimum, maximum, label in (
            (request.history_limit, 1, cls.MAX_HISTORY_LIMIT, "history_limit"),
            (request.memory_limit, 1, cls.MAX_MEMORY_LIMIT, "memory_limit"),
            (request.max_tokens, 32, cls.MAX_TOKEN_BUDGET, "max_tokens"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ContextValidationError(f"{label} خارج از محدوده مجاز است")
        if not isinstance(request.include_candidates, bool):
            raise ContextValidationError("include_candidates باید مقدار بولی داشته باشد")
        if not isinstance(request.memory_scopes, tuple) or len(request.memory_scopes) > cls.MAX_MEMORY_SCOPES:
            raise ContextValidationError("memory_scopes باید یک tuple صریح با حداکثر ۱۰ محدوده باشد")
        seen: set[tuple[str, str, str]] = set()
        for scope in request.memory_scopes:
            if not isinstance(scope, MemoryScope):
                raise ContextValidationError("هر محدوده حافظه باید از نوع MemoryScope باشد")
            if scope.owner_id != request.owner_id:
                raise ContextValidationError("مالک محدوده حافظه با مالک درخواست یکسان نیست")
            key = (scope.scope_type, scope.scope_id, scope.owner_id)
            if key in seen:
                raise ContextValidationError("محدوده حافظه تکراری است")
            seen.add(key)

    def assemble(self, request: ContextRequest) -> ContextPackage:
        """Select recent history and explicitly scoped memories within a fixed budget."""
        self._validate_request(request)
        query = request.query.strip()
        candidates: list[ContextItem] = []

        history = self.conversations.get_recent_messages(
            request.conversation_id, limit=request.history_limit
        )
        # The current user turn is already supplied separately as the query.
        if history and history[-1].role == "user" and self._normalize(history[-1].content) == self._normalize(query):
            history = history[:-1]

        total = len(history)
        for index, message in enumerate(history):
            if not message.content.strip():
                continue
            message_id = message.message_id
            source_ref = f"message:{message_id}" if message_id is not None else f"conversation:{request.conversation_id}:history:{index}"
            candidates.append(
                ContextItem(
                    source_type="conversation",
                    source_ref=source_ref,
                    content=message.content,
                    role=message.role,
                    model=message.model,
                    created_at=message.timestamp,
                    relevance_score=conversation_recency_score(index, total),
                    trust_status="historical_unverified",
                    provenance={
                        "source": "conversation_history",
                        "conversation_id": request.conversation_id,
                        "message_id": message_id,
                        "model": message.model,
                    },
                )
            )

        if request.memory_scopes and self.memory is None:
            raise ContextConfigurationError("Memory Service برای محدوده‌های درخواستی پیکربندی نشده است")

        memory_items: list[ContextItem] = []
        if self.memory is not None:
            for scope in request.memory_scopes:
                results = self.memory.retrieve(
                    scope,
                    query,
                    limit=request.memory_limit,
                    include_candidates=request.include_candidates,
                )
                for result in results:
                    memory = result.memory
                    memory_items.append(
                        ContextItem(
                            source_type="memory",
                            source_ref=f"memory:{memory.id}",
                            content=memory.content,
                            relevance_score=result.score,
                            trust_status=memory.status,
                            provenance={
                                **memory.provenance,
                                "memory_id": memory.id,
                                "memory_type": memory.memory_type,
                                "scope_type": memory.scope_type,
                                "scope_id": memory.scope_id,
                                "owner_id": memory.owner_id,
                                "source_type": memory.source_type,
                                "source_ref": memory.source_ref,
                                "verified_by": memory.verified_by,
                            },
                            created_at=memory.created_at,
                        )
                    )

        # Apply one aggregate memory limit across all explicitly supplied scopes.
        memory_items.sort(key=selection_key)
        omitted = max(0, len(memory_items) - request.memory_limit)
        memory_items = memory_items[:request.memory_limit]

        # Prefer memory provenance for exact duplicates rather than shadowing it with chat.
        deduplicated: list[ContextItem] = []
        seen_content: set[str] = set()
        for item in memory_items + candidates:
            normalized = self._normalize(item.content)
            if normalized in seen_content:
                continue
            seen_content.add(normalized)
            deduplicated.append(item)

        ranked = sorted(deduplicated, key=selection_key)
        selected: list[ContextItem] = []
        estimated_tokens = 0
        for item in ranked:
            item_tokens = self.token_budget.estimate(item.content)
            if estimated_tokens + item_tokens > request.max_tokens:
                omitted += 1
                continue
            selected.append(item)
            estimated_tokens += item_tokens

        selected.sort(key=presentation_key)
        return ContextPackage(
            conversation_id=request.conversation_id,
            query=query,
            items=tuple(selected),
            estimated_tokens=estimated_tokens,
            token_budget=request.max_tokens,
            omitted_items=omitted,
        )

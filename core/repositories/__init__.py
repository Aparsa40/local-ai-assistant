"""Domain persistence repositories; optional domains are imported lazily."""
from .catalog_repository import CatalogRepository
from .approval_repository import ApprovalRepository
from .audit_repository import AuditRepository
from .message_repository import MessageRepository
from .memory_repository import MemoryRepository
from .profile_repository import ProfileRepository
from .permission_repository import PermissionRepository
from .runtime_repository import RuntimeRepository
from .session_repository import SessionRepository

__all__ = [
    "CatalogRepository",
    "ApprovalRepository",
    "AuditRepository",
    "MessageRepository",
    "MemoryRepository",
    "KnowledgeRepository",
    "ProfileRepository",
    "PermissionRepository",
    "RuntimeRepository",
    "SessionRepository",
]


def __getattr__(name: str):
    if name == "KnowledgeRepository":
        from .knowledge_repository import KnowledgeRepository
        return KnowledgeRepository
    raise AttributeError(name)

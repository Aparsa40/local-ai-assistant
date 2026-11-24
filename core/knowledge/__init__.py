"""Knowledge Storage public contracts, loaded lazily to avoid ORM import cycles."""
from __future__ import annotations

__all__ = [
    "DenyAllKnowledgeAccessPolicy",
    "KnowledgeAccessDeniedError",
    "KnowledgeNotFoundError",
    "KnowledgeScope",
    "KnowledgeSearchResult",
    "KnowledgeService",
    "KnowledgeValidationError",
    "ManagedFileStorage",
    "ManagedFileStorageError",
]


def __getattr__(name: str):
    if name in {
        "DenyAllKnowledgeAccessPolicy",
        "KnowledgeAccessDeniedError",
        "KnowledgeNotFoundError",
        "KnowledgeScope",
        "KnowledgeSearchResult",
        "KnowledgeService",
        "KnowledgeValidationError",
    }:
        from . import service
        return getattr(service, name)
    if name in {"ManagedFileStorage", "ManagedFileStorageError"}:
        from . import storage
        return getattr(storage, name)
    raise AttributeError(name)

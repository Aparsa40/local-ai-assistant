"""Application service for controlled, provenance-aware memory lifecycle."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from core.database import MemoryRecord, utcnow_naive
from core.repositories.memory_repository import MemoryRepository

from .policies import DenyAllMemoryAccessPolicy, MemoryAccessPolicy, MemoryRetentionPolicy
from .scoring import score_memory
from .types import MemoryRecordView, MemoryScope, MemorySearchResult


class MemoryServiceError(Exception):
    """Base class for expected memory-domain errors."""


class MemoryAccessDeniedError(MemoryServiceError):
    """The injected policy did not authorize the requested operation."""


class MemoryNotFoundError(MemoryServiceError):
    """No memory exists in the supplied scope."""


class MemoryValidationError(MemoryServiceError, ValueError):
    """A memory payload or lifecycle transition is invalid."""


class MemoryConflictError(MemoryServiceError):
    """A deduplication key already identifies a different active candidate."""


class MemoryService:
    """Owns memory validation, lifecycle, retrieval, and conservative ranking."""

    MEMORY_TYPES = {"short_term", "long_term", "episodic", "semantic"}
    SCOPE_TYPES = {"user", "conversation", "task", "global"}
    SOURCE_TYPES = {"user", "assistant", "system", "tool", "import"}
    MAX_CONTENT_LENGTH = 12000
    MAX_RETENTION_DAYS = 36500
    _SECRET_PATTERNS = (
        re.compile(r"""(?i)["']?\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)["']?\s*[:=]\s*["']?[^"'\s,;}]+"""),
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    )

    def __init__(
        self,
        db,
        access_policy: MemoryAccessPolicy | None = None,
        retention_policy: MemoryRetentionPolicy | None = None,
    ) -> None:
        self.repository = MemoryRepository(db)
        self.access_policy = access_policy or DenyAllMemoryAccessPolicy()
        self.retention_policy = retention_policy or MemoryRetentionPolicy()

    def _authorize(self, scope: MemoryScope, action: str) -> None:
        if not isinstance(scope.scope_type, str) or scope.scope_type not in self.SCOPE_TYPES:
            raise MemoryValidationError("نوع محدوده حافظه معتبر نیست")
        if not isinstance(scope.scope_id, str) or not scope.scope_id or len(scope.scope_id) > 160:
            raise MemoryValidationError("شناسه محدوده حافظه معتبر نیست")
        if not isinstance(scope.owner_id, str) or not scope.owner_id or len(scope.owner_id) > 160:
            raise MemoryValidationError("شناسه مالک حافظه معتبر نیست")
        if not self.access_policy.authorize(scope.scope_type, scope.scope_id, scope.owner_id, action):
            raise MemoryAccessDeniedError("دسترسی به حافظه برای این محدوده مجاز نشده است")

    @staticmethod
    def _view(record: MemoryRecord) -> MemoryRecordView:
        return MemoryRecordView(
            id=record.id,
            memory_type=record.memory_type,
            content=record.content,
            scope_type=record.scope_type,
            scope_id=record.scope_id,
            owner_id=record.owner_id,
            source_type=record.source_type,
            source_ref=record.source_ref,
            provenance=copy.deepcopy(record.provenance or {}),
            confidence=record.confidence,
            importance=record.importance,
            status=record.status,
            verified_by=record.verified_by,
            retention_days=record.retention_days,
            expires_at=record.expires_at,
            superseded_by_id=record.superseded_by_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_accessed_at=record.last_accessed_at,
        )

    @classmethod
    def _validate_content(cls, content: str) -> str:
        if not isinstance(content, str):
            raise MemoryValidationError("محتوای حافظه باید متن باشد")
        value = " ".join(content.split())
        if not value:
            raise MemoryValidationError("محتوای حافظه نمی‌تواند خالی باشد")
        if len(value) > cls.MAX_CONTENT_LENGTH:
            raise MemoryValidationError("محتوای حافظه بیش از حد مجاز است")
        if any(pattern.search(value) for pattern in cls._SECRET_PATTERNS):
            raise MemoryValidationError("ذخیره رمز عبور، کلید API یا توکن در حافظه مجاز نیست")
        return value

    @staticmethod
    def _validate_provenance(provenance: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(provenance, dict) or not provenance:
            raise MemoryValidationError("اطلاعات منشأ حافظه الزامی است")
        try:
            encoded = json.dumps(provenance, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("اطلاعات منشأ باید JSON-compatible باشد") from exc
        if len(encoded) > 8000:
            raise MemoryValidationError("اطلاعات منشأ بیش از حد مجاز است")
        if any(pattern.search(encoded) for pattern in MemoryService._SECRET_PATTERNS):
            raise MemoryValidationError("ذخیره اطلاعات محرمانه در منشأ حافظه مجاز نیست")
        return dict(provenance)

    @staticmethod
    def _validate_signal(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise MemoryValidationError(f"{name} باید عددی بین ۰ تا ۱۰۰ باشد")
        return value

    def create_candidate(
        self,
        scope: MemoryScope,
        *,
        memory_type: str,
        content: str,
        source_type: str,
        provenance: dict[str, Any],
        source_ref: str | None = None,
        dedup_key: str | None = None,
        confidence: int = 50,
        importance: int = 50,
        retention_days: int | None = None,
    ) -> MemoryRecordView:
        self._authorize(scope, "create")
        if not isinstance(memory_type, str) or memory_type not in self.MEMORY_TYPES:
            raise MemoryValidationError("نوع حافظه معتبر نیست")
        if not isinstance(source_type, str) or source_type not in self.SOURCE_TYPES:
            raise MemoryValidationError("نوع منبع حافظه معتبر نیست")
        normalized_content = self._validate_content(content)
        safe_provenance = self._validate_provenance(provenance)
        confidence = self._validate_signal(confidence, "confidence")
        importance = self._validate_signal(importance, "importance")
        if retention_days is not None and (
            isinstance(retention_days, bool)
            or not isinstance(retention_days, int)
            or not 1 <= retention_days <= self.MAX_RETENTION_DAYS
        ):
            raise MemoryValidationError("مدت نگهداری باید بین ۱ تا ۳۶۵۰۰ روز باشد")
        if dedup_key is not None and (not isinstance(dedup_key, str) or not dedup_key.strip() or len(dedup_key) > 255):
            raise MemoryValidationError("کلید تشخیص تکرار معتبر نیست")
        if source_ref is not None and (not isinstance(source_ref, str) or not source_ref.strip() or len(source_ref) > 255):
            raise MemoryValidationError("شناسه مرجع منبع معتبر نیست")
        if source_ref is not None and any(pattern.search(source_ref) for pattern in self._SECRET_PATTERNS):
            raise MemoryValidationError("مرجع منبع نباید حاوی اطلاعات محرمانه باشد")

        if dedup_key:
            existing_key = self.repository.find_dedup_key(
                dedup_key, scope.scope_type, scope.scope_id, scope.owner_id
            )
            if existing_key:
                if " ".join(existing_key.content.casefold().split()) == normalized_content.casefold():
                    return self._view(existing_key)
                raise MemoryConflictError("برای این کلید، حافظه فعال دیگری با محتوای متفاوت وجود دارد")

        duplicate = self.repository.find_duplicate(
            memory_type, scope.scope_type, scope.scope_id, scope.owner_id, normalized_content.casefold()
        )
        if duplicate:
            return self._view(duplicate)

        expiry = self.retention_policy.expiry_for(memory_type, retention_days)
        effective_retention = (
            retention_days if retention_days is not None
            else self.retention_policy.DEFAULT_DAYS[memory_type]
        )
        record = MemoryRecord(
            memory_type=memory_type,
            content=normalized_content,
            dedup_key=dedup_key,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            owner_id=scope.owner_id,
            source_type=source_type,
            source_ref=source_ref,
            provenance=safe_provenance,
            confidence=confidence,
            importance=importance,
            status="candidate",
            retention_days=effective_retention,
            expires_at=expiry,
        )
        return self._view(self.repository.add(record))

    def get(self, scope: MemoryScope, memory_id: int) -> MemoryRecordView:
        self._authorize(scope, "read")
        record = self.repository.get(memory_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if record is None or record.status == "expired":
            raise MemoryNotFoundError("حافظه در این محدوده پیدا نشد")
        now = utcnow_naive()
        if record.expires_at and record.expires_at <= now and record.status in {"candidate", "active"}:
            record.status = "expired"
            self.repository.save(record)
            raise MemoryNotFoundError("حافظه منقضی شده است")
        return self._view(self.repository.touch(record, now))

    def activate(self, scope: MemoryScope, memory_id: int, *, verified_by: str) -> MemoryRecordView:
        self._authorize(scope, "activate")
        reviewer = verified_by.strip() if isinstance(verified_by, str) else ""
        if not reviewer or len(reviewer) > 160:
            raise MemoryValidationError("شناسه بازبین برای تأیید حافظه الزامی است")
        record = self.repository.get(memory_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if record is None:
            raise MemoryNotFoundError("حافظه در این محدوده پیدا نشد")
        if record.status != "candidate":
            raise MemoryValidationError("فقط حافظه کاندیدا قابل تأیید است")
        if record.expires_at and record.expires_at <= utcnow_naive():
            record.status = "expired"
            self.repository.save(record)
            raise MemoryValidationError("حافظه منقضی‌شده قابل تأیید نیست")
        record.status = "active"
        record.verified_by = reviewer
        record.updated_at = utcnow_naive()
        return self._view(self.repository.save(record))

    def update(
        self,
        scope: MemoryScope,
        memory_id: int,
        *,
        content: str | None = None,
        confidence: int | None = None,
        importance: int | None = None,
        retention_days: int | None = None,
    ) -> MemoryRecordView:
        self._authorize(scope, "update")
        record = self.repository.get(memory_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if record is None:
            raise MemoryNotFoundError("حافظه در این محدوده پیدا نشد")
        if record.status not in {"candidate", "active"}:
            raise MemoryValidationError("این وضعیت حافظه قابل ویرایش نیست")
        if content is not None:
            updated_content = self._validate_content(content)
            if updated_content != record.content:
                if record.dedup_key:
                    keyed = self.repository.find_dedup_key(
                        record.dedup_key, scope.scope_type, scope.scope_id, scope.owner_id
                    )
                    if keyed and keyed.id != record.id:
                        raise MemoryConflictError("کلید تشخیص تکرار به حافظه دیگری تعلق دارد")
                duplicate = self.repository.find_duplicate(
                    record.memory_type, scope.scope_type, scope.scope_id, scope.owner_id, updated_content.casefold()
                )
                if duplicate and duplicate.id != record.id:
                    raise MemoryConflictError("محتوای جدید با یک حافظه موجود تکراری است")
                history = list((record.provenance or {}).get("revision_history", []))
                history.append({
                    "at": utcnow_naive().isoformat(),
                    "previous_sha256": hashlib.sha256(record.content.encode("utf-8")).hexdigest(),
                })
                record.provenance = {**(record.provenance or {}), "revision_history": history[-20:]}
                record.content = updated_content
        if confidence is not None:
            record.confidence = self._validate_signal(confidence, "confidence")
        if importance is not None:
            record.importance = self._validate_signal(importance, "importance")
        if retention_days is not None:
            if isinstance(retention_days, bool) or not isinstance(retention_days, int) or not 1 <= retention_days <= self.MAX_RETENTION_DAYS:
                raise MemoryValidationError("مدت نگهداری باید بین ۱ تا ۳۶۵۰۰ روز باشد")
            record.retention_days = retention_days
            record.expires_at = self.retention_policy.expiry_for(record.memory_type, retention_days)
        record.updated_at = utcnow_naive()
        return self._view(self.repository.save(record))

    def supersede(self, scope: MemoryScope, memory_id: int, replacement_id: int) -> MemoryRecordView:
        self._authorize(scope, "supersede")
        if memory_id == replacement_id:
            raise MemoryValidationError("حافظه نمی‌تواند جایگزین خودش شود")
        current = self.repository.get(memory_id, scope.scope_type, scope.scope_id, scope.owner_id)
        replacement = self.repository.get(replacement_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if current is None or replacement is None:
            raise MemoryNotFoundError("حافظه مبدأ یا جایگزین پیدا نشد")
        if current.status not in {"candidate", "active"} or replacement.status != "active":
            raise MemoryValidationError("جایگزینی فقط با یک حافظه فعال امکان‌پذیر است")
        if current.memory_type != replacement.memory_type:
            raise MemoryValidationError("نوع حافظه جایگزین باید یکسان باشد")
        current.status = "superseded"
        current.superseded_by_id = replacement.id
        current.updated_at = utcnow_naive()
        return self._view(self.repository.save(current))

    def expire_due(self, scope: MemoryScope) -> int:
        self._authorize(scope, "expire")
        return self.repository.expire_due(scope.scope_type, scope.scope_id, scope.owner_id, utcnow_naive())

    def delete(self, scope: MemoryScope, memory_id: int) -> None:
        self._authorize(scope, "delete")
        record = self.repository.get(memory_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if record is None:
            raise MemoryNotFoundError("حافظه در این محدوده پیدا نشد")
        self.repository.delete(record)

    def retrieve(
        self,
        scope: MemoryScope,
        query: str,
        *,
        limit: int = 10,
        include_candidates: bool = False,
    ) -> list[MemorySearchResult]:
        self._authorize(scope, "read")
        if not isinstance(query, str) or not query.strip():
            raise MemoryValidationError("عبارت بازیابی نمی‌تواند خالی باشد")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MemoryValidationError("تعداد نتایج باید بین ۱ تا ۱۰۰ باشد")
        now = utcnow_naive()
        self.repository.expire_due(scope.scope_type, scope.scope_id, scope.owner_id, now)
        statuses = ("active", "candidate") if include_candidates else ("active",)
        records = self.repository.list_scope(scope.scope_type, scope.scope_id, scope.owner_id, statuses)
        ranked = []
        for record in records:
            score, matched = score_memory(
                record.content, query, record.importance, record.confidence, record.updated_at, now
            )
            if matched:
                ranked.append((score, matched, record))
        ranked.sort(key=lambda item: (-item[0], -item[2].updated_at.timestamp(), item[2].id))
        results = []
        for score, matched, record in ranked[:limit]:
            self.repository.touch(record, now)
            results.append(MemorySearchResult(self._view(record), score, matched))
        return results

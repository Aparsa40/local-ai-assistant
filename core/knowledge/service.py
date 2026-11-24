"""Scoped Knowledge source lifecycle, extraction artifacts, chunking, and FTS retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from core.repositories.knowledge_repository import KnowledgeRepository
from sqlalchemy.orm import Session

from core.database import utcnow_naive
from .models import KnowledgeArtifactRecord, KnowledgeChunkRecord, KnowledgeFileRecord, KnowledgeSourceRecord
from .storage import ManagedFileStorage


class KnowledgeValidationError(ValueError):
    """Raised when Knowledge input violates the storage contract."""


class KnowledgeAccessDeniedError(PermissionError):
    """Raised when a Knowledge operation is not explicitly authorized."""


class KnowledgeNotFoundError(LookupError):
    """Raised when a source is not present in the requested scope."""


@dataclass(frozen=True)
class KnowledgeScope:
    scope_type: str
    scope_id: str
    owner_id: str = "local"


@dataclass(frozen=True)
class KnowledgeSearchResult:
    chunk_id: int
    source_id: str
    title: str
    content: str
    source_type: str
    uri: str | None
    rank: float


class DenyAllKnowledgeAccessPolicy:
    """Safe default: Knowledge is inaccessible until an application policy is injected."""

    def authorize(self, scope_type: str, scope_id: str, owner_id: str, action: str) -> bool:
        return False


class KnowledgeService:
    """Domain service; callers must supply an explicit scope and access policy."""

    SOURCE_TYPES = {"file", "url", "text", "manual"}
    MAX_TEXT_CHARS = 5_000_000
    SECRET_PATTERN = re.compile(r"""(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)["']?\s*[:=]""")

    def __init__(
        self,
        session: Session,
        *,
        access_policy=None,
        file_storage: ManagedFileStorage | None = None,
    ) -> None:
        self.db = session
        self.repository = KnowledgeRepository(session)
        self.access_policy = access_policy or DenyAllKnowledgeAccessPolicy()
        self.file_storage = file_storage or ManagedFileStorage()

    @staticmethod
    def _validate_scope(scope: KnowledgeScope) -> None:
        if not isinstance(scope, KnowledgeScope):
            raise KnowledgeValidationError("An explicit KnowledgeScope is required")
        if not isinstance(scope.scope_type, str) or scope.scope_type not in {"user", "conversation", "task", "global"}:
            raise KnowledgeValidationError("Unsupported Knowledge scope type")
        if not isinstance(scope.scope_id, str) or not isinstance(scope.owner_id, str) or not scope.scope_id.strip() or not scope.owner_id.strip():
            raise KnowledgeValidationError("Knowledge scope and owner identifiers are required")

    def _authorize(self, scope: KnowledgeScope, action: str) -> None:
        self._validate_scope(scope)
        if not self.access_policy.authorize(scope.scope_type, scope.scope_id, scope.owner_id, action):
            raise KnowledgeAccessDeniedError("Knowledge access denied by default-deny policy")

    def _source(self, scope: KnowledgeScope, source_id: str, action: str) -> KnowledgeSourceRecord:
        self._authorize(scope, action)
        row = self.repository.get_source(source_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if row is None:
            raise KnowledgeNotFoundError("Knowledge source not found in the requested scope")
        return row

    def create_source(
        self,
        scope: KnowledgeScope,
        *,
        source_type: str,
        title: str,
        uri: str | None = None,
        mime_type: str | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeSourceRecord:
        self._authorize(scope, "write")
        if source_type not in self.SOURCE_TYPES:
            raise KnowledgeValidationError("Unsupported Knowledge source type")
        clean_title = title.strip() if isinstance(title, str) else ""
        if not clean_title or len(clean_title) > 300:
            raise KnowledgeValidationError("Source title must contain 1–300 characters")
        if uri is not None and (not isinstance(uri, str) or len(uri) > 4000):
            raise KnowledgeValidationError("Source URI is invalid or too long")
        if metadata is not None and not isinstance(metadata, dict):
            raise KnowledgeValidationError("Source metadata must be an object")
        try:
            metadata_text = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise KnowledgeValidationError("Source metadata must be JSON-serializable") from exc
        if self.SECRET_PATTERN.search(metadata_text) or (uri and (self.SECRET_PATTERN.search(uri) or re.search(r"://[^/@:]+:[^/@]+@", uri))):
            raise KnowledgeValidationError("Credential-like material cannot be stored in Knowledge metadata")
        source = KnowledgeSourceRecord(
            id=uuid4().hex,
            source_type=source_type,
            title=clean_title,
            uri=uri,
            owner_id=scope.owner_id,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            status="registered",
            mime_type=mime_type,
            metadata_json=metadata or {},
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def get_source(self, scope: KnowledgeScope, source_id: str) -> KnowledgeSourceRecord:
        return self._source(scope, source_id, "read")

    def store_original_file(
        self,
        scope: KnowledgeScope,
        source_id: str,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> KnowledgeFileRecord:
        source = self._source(scope, source_id, "write")
        safe_name = filename.replace(chr(92), "/").split("/")[-1].strip() if isinstance(filename, str) else ""
        if not safe_name or len(safe_name) > 255 or safe_name in {".", ".."}:
            raise KnowledgeValidationError("Original filename is invalid")
        storage_key, size_bytes, digest = self.file_storage.store(content)
        next_version = source.version + 1
        record = KnowledgeFileRecord(
            id=uuid4().hex,
            source_id=source.id,
            source_version=next_version,
            storage_key=storage_key,
            original_filename=safe_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=digest,
        )
        source.mime_type = mime_type or source.mime_type
        source.byte_size = size_bytes
        source.content_hash = digest
        source.version = next_version
        source.updated_at = utcnow_naive()
        self.db.add(record)
        try:
            self.db.commit()
            self.db.refresh(record)
            return record
        except Exception:
            self.db.rollback()
            self.file_storage.delete(storage_key)
            raise

    def read_original_file(self, scope: KnowledgeScope, file_id: str) -> bytes:
        self._authorize(scope, "read")
        record = self.repository.get_file(file_id, scope.scope_type, scope.scope_id, scope.owner_id)
        if record is None:
            raise KnowledgeNotFoundError("Managed source file not found in the requested scope")
        return self.file_storage.read(record.storage_key)

    @staticmethod
    def _chunks(content: str, chunk_size: int, overlap: int):
        step = chunk_size - overlap
        for start in range(0, len(content), step):
            end = min(len(content), start + chunk_size)
            chunk = content[start:end].strip()
            if chunk:
                yield start, end, chunk
            if end >= len(content):
                break

    def index_extracted_text(
        self,
        scope: KnowledgeScope,
        source_id: str,
        extracted_text: str,
        *,
        extractor: str = "manual",
        extractor_version: str = "1",
        chunk_size: int = 1200,
        overlap: int = 120,
    ) -> int:
        source = self._source(scope, source_id, "write")
        if not isinstance(extracted_text, str) or not extracted_text.strip():
            raise KnowledgeValidationError("Extracted text must not be empty")
        if len(extracted_text) > self.MAX_TEXT_CHARS:
            raise KnowledgeValidationError("Extracted text exceeds the configured limit")
        if chunk_size < 100 or chunk_size > 8000 or overlap < 0 or overlap >= chunk_size:
            raise KnowledgeValidationError("Chunk size or overlap is outside the supported range")
        normalized = extracted_text.strip()
        if self.SECRET_PATTERN.search(normalized):
            raise KnowledgeValidationError("Credential-like material cannot be indexed as Knowledge")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        next_version = source.version + 1
        now = utcnow_naive()

        # Replace the active lexical index atomically while preserving extraction history.
        self.repository.delete_source_chunks(source.id)
        self.db.add(
            KnowledgeArtifactRecord(
                id=uuid4().hex,
                source_id=source.id,
                source_version=next_version,
                artifact_type="extracted_text",
                content=normalized,
                status="unreviewed",
                provenance={
                    "extractor": extractor[:120],
                    "extractor_version": extractor_version[:80],
                    "content_sha256": digest,
                    "created_at": now.isoformat(),
                },
            )
        )
        count = 0
        for ordinal, (start, end, chunk) in enumerate(self._chunks(normalized, chunk_size, overlap)):
            self.db.add(
                KnowledgeChunkRecord(
                    source_id=source.id,
                    ordinal=ordinal,
                    content=chunk,
                    content_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    locator={"char_start": start, "char_end": end, "source_version": next_version},
                )
            )
            count += 1
        source.content_hash = digest
        source.version = next_version
        source.status = "indexed"
        source.indexed_at = now
        source.updated_at = now
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return count

    def search(
        self,
        scope: KnowledgeScope,
        query: str,
        *,
        limit: int = 10,
    ) -> list[KnowledgeSearchResult]:
        self._authorize(scope, "read")
        if not isinstance(query, str):
            raise KnowledgeValidationError("Search query must be text")
        if limit < 1 or limit > 50:
            raise KnowledgeValidationError("Search limit must be between 1 and 50")
        terms = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
        if not terms:
            return []
        # Quote every token and build the MATCH expression ourselves to avoid FTS syntax injection.
        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:20])
        rows = self.repository.search_rows(
            scope.scope_type, scope.scope_id, scope.owner_id, match_query, limit
        )
        return [
            KnowledgeSearchResult(
                chunk_id=row["chunk_id"],
                source_id=row["source_id"],
                title=row["title"],
                content=row["content"],
                source_type=row["source_type"],
                uri=row["uri"],
                rank=float(row["rank"]),
            )
            for row in rows
        ]

    def archive_source(self, scope: KnowledgeScope, source_id: str) -> KnowledgeSourceRecord:
        source = self._source(scope, source_id, "write")
        source.status = "archived"
        source.archived_at = utcnow_naive()
        self.db.commit()
        self.db.refresh(source)
        return source

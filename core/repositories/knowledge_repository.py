"""Persistence boundary for Knowledge source metadata and lexical retrieval."""
from __future__ import annotations

from sqlalchemy import text

from core.knowledge.models import KnowledgeFileRecord, KnowledgeSourceRecord, KnowledgeChunkRecord
from .base import BaseRepository


class KnowledgeRepository(BaseRepository):
    """Owns Knowledge ORM queries and FTS SQL; callers provide explicit scope values."""

    def get_source(self, source_id: str, scope_type: str, scope_id: str, owner_id: str):
        return (
            self.db.query(KnowledgeSourceRecord)
            .filter(
                KnowledgeSourceRecord.id == source_id,
                KnowledgeSourceRecord.scope_type == scope_type,
                KnowledgeSourceRecord.scope_id == scope_id,
                KnowledgeSourceRecord.owner_id == owner_id,
                KnowledgeSourceRecord.status != "deleted",
            )
            .first()
        )

    def get_file(self, file_id: str, scope_type: str, scope_id: str, owner_id: str):
        return (
            self.db.query(KnowledgeFileRecord)
            .join(KnowledgeSourceRecord, KnowledgeSourceRecord.id == KnowledgeFileRecord.source_id)
            .filter(
                KnowledgeFileRecord.id == file_id,
                KnowledgeSourceRecord.scope_type == scope_type,
                KnowledgeSourceRecord.scope_id == scope_id,
                KnowledgeSourceRecord.owner_id == owner_id,
                KnowledgeSourceRecord.status != "deleted",
            )
            .first()
        )

    def delete_source_chunks(self, source_id: str) -> None:
        self.db.query(KnowledgeChunkRecord).filter(
            KnowledgeChunkRecord.source_id == source_id
        ).delete(synchronize_session=False)

    def search_rows(self, scope_type: str, scope_id: str, owner_id: str, match_query: str, limit: int):
        return self.db.execute(
            text(
                "SELECT c.id AS chunk_id, c.source_id AS source_id, s.title AS title, "
                "c.content AS content, s.source_type AS source_type, s.uri AS uri, "
                "bm25(knowledge_chunks_fts) AS rank "
                "FROM knowledge_chunks_fts "
                "JOIN knowledge_chunks AS c ON c.id = knowledge_chunks_fts.rowid "
                "JOIN knowledge_sources AS s ON s.id = c.source_id "
                "WHERE knowledge_chunks_fts MATCH :match_query "
                "AND s.owner_id = :owner_id AND s.scope_type = :scope_type "
                "AND s.scope_id = :scope_id AND s.status = 'indexed' "
                "ORDER BY rank ASC LIMIT :limit"
            ),
            {
                "match_query": match_query,
                "owner_id": owner_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "limit": limit,
            },
        ).mappings().all()

"""SQLAlchemy records owned by Knowledge Storage."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from core.database import Base, utcnow_naive


class KnowledgeSourceRecord(Base):
    __tablename__ = "knowledge_sources"

    id = Column(String(32), primary_key=True)
    source_type = Column(String(20), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    uri = Column(Text, nullable=True)
    owner_id = Column(String(160), nullable=False, index=True)
    scope_type = Column(String(40), nullable=False, index=True)
    scope_id = Column(String(160), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="registered", index=True)
    mime_type = Column(String(160), nullable=True)
    byte_size = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
    indexed_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)


class KnowledgeFileRecord(Base):
    __tablename__ = "knowledge_files"

    id = Column(String(32), primary_key=True)
    source_id = Column(String(32), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    source_version = Column(Integer, nullable=False)
    storage_key = Column(String(64), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(160), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(32), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    locator = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal", name="uq_knowledge_chunk_source_ordinal"),
        Index("ix_knowledge_chunks_source_ordinal", "source_id", "ordinal"),
    )


class KnowledgeArtifactRecord(Base):
    __tablename__ = "knowledge_artifacts"

    id = Column(String(32), primary_key=True)
    source_id = Column(String(32), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    source_version = Column(Integer, nullable=False)
    artifact_type = Column(String(40), nullable=False, index=True)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="unreviewed", index=True)
    provenance = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

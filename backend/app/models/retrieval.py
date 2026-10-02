"""Searchable chunks of documents (ARCHITECTURE.md sections 5 and 7)."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import CreatedAt, UUIDPk
from app.models.content import SOURCE_TIERS

# Must equal retrieval.yaml embeddings.dimensions (a test checks this).
EMBEDDING_DIMENSIONS = 384


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID]
    # Copied from the document so searches can filter without a join.
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    source_tier: Mapped[str] = mapped_column(
        Enum(*SOURCE_TIERS, name="source_tier", create_type=False)
    )
    page_no: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger)
    heading_path: Mapped[str] = mapped_column(Text, server_default="", default="")
    content: Mapped[str] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str] = mapped_column(String(100))
    # Headings weigh more than body text in keyword ranking.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', heading_path), 'A') || "
            "setweight(to_tsvector('english', content), 'B')",
            persisted=True,
        ),
    )
    created_at: Mapped[CreatedAt]

    __table_args__ = (
        # The chunk's owner is the document's owner.
        ForeignKeyConstraint(
            ["document_id", "user_id"],
            ["documents.id", "documents.user_id"],
            name="fk_chunks_document_same_user",
            ondelete="CASCADE",
        ),
        Index("ix_chunks_document_page", "document_id", "page_no"),
        Index("ix_chunks_user_module", "user_id", "module_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

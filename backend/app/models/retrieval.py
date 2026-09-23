"""Tables for retrieval (Phase 4): the chunk corpus and the research log.

    repositories 1 ── * code_chunks   (the retrievable units; ids are deterministic)
    retrieval_logs                    (one row per search, kept for research evaluation)

Vectors and BM25 postings live in files under `INDEX_STORAGE_DIR`, not in the database:
they are large, binary, and rebuilt as a whole. The rows here hold the text and the
metadata a result needs to be citable.
"""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class CodeChunk(UUIDPrimaryKeyMixin, Base):
    """A retrievable piece of a repository: a function, a method, a class header,
    module-level code, or a documentation section.

    `id` is a deterministic uuid5 of the repository, path, symbol and content, so the
    same code keeps the same chunk id across re-indexing and research results stay
    comparable.
    """

    __tablename__ = "code_chunks"
    __table_args__ = (
        Index("ix_code_chunks_repository_id_file_path", "repository_id", "file_path"),
        Index("ix_code_chunks_repository_id_chunk_type", "repository_id", "chunk_type"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    file_path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(32))
    # symbol | symbol_header | symbol_part | module | section | window
    chunk_type: Mapped[str] = mapped_column(String(24))
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"), index=True
    )
    symbol_name: Mapped[str | None] = mapped_column(String(512))
    symbol_type: Mapped[str | None] = mapped_column(String(32))
    qualified_name: Mapped[str | None] = mapped_column(String(2048))
    parent_symbol: Mapped[str | None] = mapped_column(String(2048))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    repository: Mapped["Repository"] = relationship()


class RetrievalLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One search, recorded for the retrieval-strategy comparison this project studies.

    The repository reference is nullable and the name/commit are copied in, so logs
    remain usable after a repository is deleted or re-indexed.
    """

    __tablename__ = "retrieval_logs"
    __table_args__ = (
        Index("ix_retrieval_logs_repository_id_strategy", "repository_id", "strategy"),
    )

    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL")
    )
    repository_name: Mapped[str | None] = mapped_column(String(255))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(32))
    reranker: Mapped[str | None] = mapped_column(String(64))
    top_k: Mapped[int] = mapped_column(Integer)
    # Fusion method and weights, candidate depths — what made this run reproducible.
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Embedding model, chunker version, BM25 parameters of the index that was searched.
    index_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_chunk_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float)
    timings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

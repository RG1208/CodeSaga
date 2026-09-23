"""Retrieval: the chunk corpus and the research log.

Tables: code_chunks (deterministic ids; the retrievable units) and retrieval_logs
(one row per search, for the retrieval-strategy comparison). BM25 postings and dense
vectors live in files under INDEX_STORAGE_DIR, not in the database.
The new repository status "embedding" needs no change: statuses are VARCHAR.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17 17:52:10.988554+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=True),
        sa.Column("repository_name", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("reranker", sa.String(length=64), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("index_info", sa.JSON(), nullable=False),
        sa.Column("result_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("timings", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_retrieval_logs_repository_id_repositories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_logs")),
    )
    op.create_index(
        "ix_retrieval_logs_repository_id_strategy",
        "retrieval_logs",
        ["repository_id", "strategy"],
        unique=False,
    )
    op.create_table(
        "code_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("chunk_type", sa.String(length=24), nullable=False),
        sa.Column("symbol_id", sa.Uuid(), nullable=True),
        sa.Column("symbol_name", sa.String(length=512), nullable=True),
        sa.Column("symbol_type", sa.String(length=32), nullable=True),
        sa.Column("qualified_name", sa.String(length=2048), nullable=True),
        sa.Column("parent_symbol", sa.String(length=2048), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_code_chunks_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_id"],
            ["code_symbols.id"],
            name=op.f("fk_code_chunks_symbol_id_code_symbols"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_chunks")),
    )
    op.create_index(
        "ix_code_chunks_repository_id_chunk_type",
        "code_chunks",
        ["repository_id", "chunk_type"],
        unique=False,
    )
    op.create_index(
        "ix_code_chunks_repository_id_file_path",
        "code_chunks",
        ["repository_id", "file_path"],
        unique=False,
    )
    op.create_index(op.f("ix_code_chunks_symbol_id"), "code_chunks", ["symbol_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_code_chunks_symbol_id"), table_name="code_chunks")
    op.drop_index("ix_code_chunks_repository_id_file_path", table_name="code_chunks")
    op.drop_index("ix_code_chunks_repository_id_chunk_type", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.drop_index("ix_retrieval_logs_repository_id_strategy", table_name="retrieval_logs")
    op.drop_table("retrieval_logs")

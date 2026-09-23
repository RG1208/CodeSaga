"""Repository ingestion: clone/index tracking, indexing jobs and the file index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

Changes to `repositories`:
* new columns: owner, branch, commit_sha, local_path, status_message,
  last_indexed_at, repo_metadata
* existing rows: branch := default_branch, owner parsed from GitHub URLs,
  status 'ready' renamed to 'completed'
* default_branch no longer defaults to 'main' (it is resolved from the remote)

New tables: indexing_jobs, repository_files.
"""

from collections.abc import Sequence
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_JOB_CONDITION = sa.text("status IN ('queued', 'running')")

_REPOSITORY_STATUSES = (
    "pending", "queued", "cloning", "analyzing", "indexing", "completed", "failed",
)  # fmt: skip


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    with op.batch_alter_table("repositories") as batch_op:
        batch_op.add_column(sa.Column("owner", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("branch", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("commit_sha", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("local_path", sa.String(length=4096), nullable=True))
        batch_op.add_column(sa.Column("status_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("repo_metadata", sa.JSON(), nullable=True))

    # --- backfill existing rows -------------------------------------------
    repositories = sa.table(
        "repositories",
        sa.column("id", sa.Uuid()),
        sa.column("url", sa.String()),
        sa.column("source_type", sa.String()),
        sa.column("owner", sa.String()),
        sa.column("branch", sa.String()),
        sa.column("default_branch", sa.String()),
        sa.column("status", sa.String()),
    )
    bind = op.get_bind()
    bind.execute(repositories.update().values(branch=repositories.c.default_branch))
    bind.execute(
        repositories.update().where(repositories.c.status == "ready").values(status="completed")
    )
    github_rows = bind.execute(
        sa.select(repositories.c.id, repositories.c.url).where(
            repositories.c.source_type == "github"
        )
    ).all()
    for row_id, url in github_rows:
        segments = urlsplit(url).path.strip("/").split("/")
        if len(segments) >= 2 and segments[0]:
            bind.execute(
                repositories.update()
                .where(repositories.c.id == row_id)
                .values(owner=segments[0])
            )

    with op.batch_alter_table("repositories") as batch_op:
        batch_op.alter_column("branch", existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column(
            "default_branch",
            existing_type=sa.String(length=255),
            existing_nullable=False,
            server_default=None,
        )

    # --- new tables ---------------------------------------------------------
    op.create_table(
        "indexing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "succeeded", "failed",
                name="jobstatus", native_enum=False, length=32,
            ),
            server_default="queued",
            nullable=False,
        ),  # fmt: skip
        sa.Column(
            "stage",
            sa.Enum(
                *_REPOSITORY_STATUSES, name="repositorystatus", native_enum=False, length=32
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("files_total", sa.Integer(), nullable=True),
        sa.Column("files_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_indexing_jobs_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indexing_jobs")),
    )
    op.create_index(
        op.f("ix_indexing_jobs_repository_id"), "indexing_jobs", ["repository_id"], unique=False
    )
    op.create_index(
        "uq_indexing_jobs_one_active_per_repository",
        "indexing_jobs",
        ["repository_id"],
        unique=True,
        postgresql_where=_ACTIVE_JOB_CONDITION,
        sqlite_where=_ACTIVE_JOB_CONDITION,
    )

    op.create_table(
        "repository_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repository_files_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repository_files")),
        sa.UniqueConstraint(
            "repository_id", "path", name=op.f("uq_repository_files_repository_id_path")
        ),
    )
    op.create_index(
        op.f("ix_repository_files_language"), "repository_files", ["language"], unique=False
    )
    op.create_index(
        op.f("ix_repository_files_repository_id"),
        "repository_files",
        ["repository_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_repository_files_repository_id"), table_name="repository_files")
    op.drop_index(op.f("ix_repository_files_language"), table_name="repository_files")
    op.drop_table("repository_files")
    op.drop_index("uq_indexing_jobs_one_active_per_repository", table_name="indexing_jobs")
    op.drop_index(op.f("ix_indexing_jobs_repository_id"), table_name="indexing_jobs")
    op.drop_table("indexing_jobs")

    # Map Phase 2 statuses back onto the Phase 1 set (pending/indexing/ready/failed).
    repositories = sa.table("repositories", sa.column("status", sa.String()))
    bind = op.get_bind()
    bind.execute(
        repositories.update().where(repositories.c.status == "completed").values(status="ready")
    )
    bind.execute(
        repositories.update()
        .where(repositories.c.status.in_(["queued", "cloning", "analyzing"]))
        .values(status="pending")
    )

    with op.batch_alter_table("repositories") as batch_op:
        batch_op.alter_column(
            "default_branch",
            existing_type=sa.String(length=255),
            existing_nullable=False,
            server_default="main",
        )
        batch_op.drop_column("repo_metadata")
        batch_op.drop_column("last_indexed_at")
        batch_op.drop_column("status_message")
        batch_op.drop_column("local_path")
        batch_op.drop_column("commit_sha")
        batch_op.drop_column("branch")
        batch_op.drop_column("owner")

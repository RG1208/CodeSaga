import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.repository import RepositoryStatus, enum_column

if TYPE_CHECKING:
    from app.models.repository import Repository


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @classmethod
    def active(cls) -> frozenset["JobStatus"]:
        return frozenset({cls.QUEUED, cls.RUNNING})


_ACTIVE_JOB_CONDITION = text("status IN ('queued', 'running')")


class IndexingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One run of the ingestion pipeline for a repository (history + live progress)."""

    __tablename__ = "indexing_jobs"
    __table_args__ = (
        # At most one queued/running job per repository, enforced by the database
        # so two simultaneous "start indexing" requests cannot both succeed.
        Index(
            "uq_indexing_jobs_one_active_per_repository",
            "repository_id",
            unique=True,
            postgresql_where=_ACTIVE_JOB_CONDITION,
            sqlite_where=_ACTIVE_JOB_CONDITION,
        ),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus), default=JobStatus.QUEUED, server_default=JobStatus.QUEUED.value
    )
    # Last pipeline stage reached; shows where a failure happened.
    stage: Mapped[RepositoryStatus] = mapped_column(
        enum_column(RepositoryStatus),
        default=RepositoryStatus.QUEUED,
        server_default=RepositoryStatus.QUEUED.value,
    )
    branch: Mapped[str] = mapped_column(String(255))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    files_total: Mapped[int | None] = mapped_column(Integer)
    files_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped["Repository"] = relationship(back_populates="jobs")

    def __repr__(self) -> str:
        return f"<IndexingJob id={self.id} status={self.status}>"

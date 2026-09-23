import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.indexing_job import IndexingJob
    from app.models.project import Project
    from app.models.repository_file import RepositoryFile


class RepositorySourceType(enum.StrEnum):
    GITHUB = "github"
    LOCAL = "local"


class RepositoryStatus(enum.StrEnum):
    """Where a repository is in the ingestion lifecycle.

    pending → queued → cloning → analyzing → indexing → parsing → embedding → completed
                                                                            ↘ failed (any stage)
    """

    PENDING = "pending"  # registered, never indexed
    QUEUED = "queued"  # indexing requested, waiting for a worker
    CLONING = "cloning"
    ANALYZING = "analyzing"
    INDEXING = "indexing"
    PARSING = "parsing"  # extracting symbols, imports and dependencies
    EMBEDDING = "embedding"  # chunking and building the BM25 + dense search indexes
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def active(cls) -> frozenset["RepositoryStatus"]:
        return frozenset(
            {cls.QUEUED, cls.CLONING, cls.ANALYZING, cls.INDEXING, cls.PARSING, cls.EMBEDDING}
        )


def enum_column(enum_cls: type[enum.StrEnum]) -> Enum:
    # Stored as VARCHAR (not a native PostgreSQL ENUM) so adding a value later
    # does not require an ALTER TYPE migration.
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


class Repository(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A source code repository (GitHub or local path) registered in a project.

    Not to be confused with the `app.repositories` package, which implements
    the *Repository design pattern* (data-access classes).
    """

    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("project_id", "url"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    # GitHub owner (user or organisation); None for local repositories.
    owner: Mapped[str | None] = mapped_column(String(255))
    # Canonical GitHub URL, or the resolved absolute path of a local repository.
    url: Mapped[str] = mapped_column(String(2048))
    source_type: Mapped[RepositorySourceType] = mapped_column(enum_column(RepositorySourceType))
    # The remote's default branch, and the branch CodeSage clones and indexes.
    default_branch: Mapped[str] = mapped_column(String(255))
    branch: Mapped[str] = mapped_column(String(255))
    # Commit and checkout location of the last *successful* index.
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    local_path: Mapped[str | None] = mapped_column(String(4096))
    status: Mapped[RepositoryStatus] = mapped_column(
        enum_column(RepositoryStatus),
        default=RepositoryStatus.PENDING,
        server_default=RepositoryStatus.PENDING.value,
        index=True,
    )
    # Human-readable explanation of the current status (e.g. why indexing failed).
    status_message: Mapped[str | None] = mapped_column(Text)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Extracted metadata (languages, manifests, last commit...); shape defined by
    # `app.schemas.repository.RepositoryMetadata`. JSON because it will evolve.
    repo_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    project: Mapped["Project"] = relationship(back_populates="repositories")
    jobs: Mapped[list["IndexingJob"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )
    files: Mapped[list["RepositoryFile"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_indexing(self) -> bool:
        return self.status in RepositoryStatus.active()

    def __repr__(self) -> str:
        return f"<Repository id={self.id} name={self.name!r}>"

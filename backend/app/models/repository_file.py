import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class RepositoryFile(UUIDPrimaryKeyMixin, Base):
    """One text file in the file index produced by the INDEXING stage.

    The index describes files (path, language, size, lines, hash); file contents
    stay on disk in the checkout. Later phases parse and chunk these files.
    """

    __tablename__ = "repository_files"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    line_count: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))

    repository: Mapped["Repository"] = relationship(back_populates="files")

    def __repr__(self) -> str:
        return f"<RepositoryFile path={self.path!r}>"

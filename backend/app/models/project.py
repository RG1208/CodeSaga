import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.user import User


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workspace that groups one or more code repositories."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    owner: Mapped["User | None"] = relationship(back_populates="projects")
    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"

from typing import TYPE_CHECKING

from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person using CodeSage. Authentication fields arrive in a later phase."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"

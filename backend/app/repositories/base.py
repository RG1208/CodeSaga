import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.base import Base


class BaseRepository[ModelT: Base]:
    """Generic CRUD helpers shared by all data-access classes."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 50) -> Sequence[ModelT]:
        return self._paginate(select(self.model), offset=offset, limit=limit)

    def count(self) -> int:
        return self._count(select(self.model))

    def add(self, entity: ModelT) -> ModelT:
        """Stage a new entity and flush so database defaults and constraints apply."""
        self.session.add(entity)
        self.session.flush()
        return entity

    def _paginate(
        self, statement: Select[tuple[ModelT]], *, offset: int, limit: int
    ) -> Sequence[ModelT]:
        # Newest first; id breaks ties so pages are stable.
        ordered = statement.order_by(self.model.created_at.desc(), self.model.id)  # type: ignore[attr-defined]
        return self.session.scalars(ordered.offset(offset).limit(limit)).all()

    def _count(self, statement: Select[tuple[ModelT]]) -> int:
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        return self.session.scalar(count_statement) or 0

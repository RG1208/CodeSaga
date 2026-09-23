import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.models.retrieval import RetrievalLog
from app.repositories.base import BaseRepository


class RetrievalLogRepository(BaseRepository[RetrievalLog]):
    model = RetrievalLog

    def record(self, **fields: Any) -> RetrievalLog:
        log = RetrievalLog(**fields)
        self.session.add(log)
        self.session.flush()
        return log

    def list_for_repository(
        self, repository_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> Sequence[RetrievalLog]:
        return self.session.scalars(
            select(RetrievalLog)
            .where(RetrievalLog.repository_id == repository_id)
            .order_by(RetrievalLog.created_at.desc(), RetrievalLog.id)
            .offset(offset)
            .limit(limit)
        ).all()

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models.retrieval import CodeChunk

_BATCH_SIZE = 500


class CodeChunkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_repository(
        self, repository_id: uuid.UUID, rows: Iterable[dict[str, Any]]
    ) -> int:
        """Swap a repository's whole chunk corpus inside the caller's transaction."""
        self.session.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository_id))
        batch: list[dict[str, Any]] = []
        written = 0
        for row in rows:
            batch.append({"repository_id": repository_id, **row})
            if len(batch) >= _BATCH_SIZE:
                written += self._insert(batch)
                batch = []
        if batch:
            written += self._insert(batch)
        return written

    def get_many(self, chunk_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, CodeChunk]:
        """Chunks by id (search hydrates its results with one query)."""
        if not chunk_ids:
            return {}
        rows = self.session.scalars(select(CodeChunk).where(CodeChunk.id.in_(chunk_ids)))
        return {chunk.id: chunk for chunk in rows}

    def count_for_repository(self, repository_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count()).where(CodeChunk.repository_id == repository_id)
            )
            or 0
        )

    def _insert(self, batch: list[dict[str, Any]]) -> int:
        self.session.execute(insert(CodeChunk), batch)
        return len(batch)

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, insert, select

from app.models.repository_file import RepositoryFile
from app.repositories.base import BaseRepository

_INSERT_BATCH_SIZE = 1000


class RepositoryFileRepository(BaseRepository[RepositoryFile]):
    model = RepositoryFile

    def replace_for_repository(
        self, repository_id: uuid.UUID, rows: Iterable[dict[str, Any]]
    ) -> int:
        """Swap a repository's whole file index in the current transaction."""
        self.session.execute(
            delete(RepositoryFile).where(RepositoryFile.repository_id == repository_id)
        )
        batch: list[dict[str, Any]] = []
        written = 0
        for row in rows:
            batch.append({"id": uuid.uuid4(), "repository_id": repository_id, **row})
            if len(batch) >= _INSERT_BATCH_SIZE:
                written += self._insert(batch)
                batch = []
        if batch:
            written += self._insert(batch)
        return written

    def count_for_repository(self, repository_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count()).where(RepositoryFile.repository_id == repository_id)
            )
            or 0
        )

    def list_paths(self, repository_id: uuid.UUID) -> Sequence[str]:
        return self.session.scalars(
            select(RepositoryFile.path)
            .where(RepositoryFile.repository_id == repository_id)
            .order_by(RepositoryFile.path)
        ).all()

    def _insert(self, batch: list[dict[str, Any]]) -> int:
        self.session.execute(insert(RepositoryFile), batch)
        return len(batch)

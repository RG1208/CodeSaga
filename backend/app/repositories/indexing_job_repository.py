import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.models.indexing_job import IndexingJob, JobStatus
from app.repositories.base import BaseRepository


class IndexingJobRepository(BaseRepository[IndexingJob]):
    model = IndexingJob

    def get_active_for_repository(self, repository_id: uuid.UUID) -> IndexingJob | None:
        return self.session.scalar(
            select(IndexingJob).where(
                IndexingJob.repository_id == repository_id,
                IndexingJob.status.in_(JobStatus.active()),
            )
        )

    def get_latest_for_repository(self, repository_id: uuid.UUID) -> IndexingJob | None:
        return self.session.scalar(
            select(IndexingJob)
            .where(IndexingJob.repository_id == repository_id)
            .order_by(IndexingJob.created_at.desc(), IndexingJob.id.desc())
            .limit(1)
        )

    def list_active(self) -> Sequence[IndexingJob]:
        return self.session.scalars(
            select(IndexingJob).where(IndexingJob.status.in_(JobStatus.active()))
        ).all()

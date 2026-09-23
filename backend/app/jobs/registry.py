"""Named job handlers and the factory that builds the configured queue."""

import uuid

from app.core.config import Settings
from app.ingestion.indexer import RepositoryIndexer
from app.jobs.base import JobContext, JobHandler, JobPayload, JobQueue
from app.jobs.queues import InlineJobQueue, ThreadJobQueue

INDEX_REPOSITORY_JOB = "repositories.index"


def _index_repository(context: JobContext, payload: JobPayload) -> None:
    RepositoryIndexer(context).run(uuid.UUID(payload["job_id"]))


JOB_HANDLERS: dict[str, JobHandler] = {
    INDEX_REPOSITORY_JOB: _index_repository,
}


def build_job_queue(settings: Settings, context: JobContext) -> JobQueue:
    if settings.job_backend == "inline":
        return InlineJobQueue(context, JOB_HANDLERS)
    return ThreadJobQueue(context, JOB_HANDLERS, max_workers=settings.job_workers)

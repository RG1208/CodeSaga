import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.ingestion.git import GitClient
from app.ingestion.storage import RepositoryStorage
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.index_store import RepositoryIndexStore
from app.retrieval.rerankers import RerankerRegistry

logger = logging.getLogger(__name__)

# Payloads contain only JSON-serialisable strings (ids), never ORM objects, so
# they can travel through a message broker unchanged.
JobPayload = dict[str, str]


@dataclass(frozen=True)
class JobContext:
    """Everything a job handler (and the API) needs, built once per process.

    Also the place where replaceable components are chosen, so tests can pass an
    offline embedding provider or a stub reranker.
    """

    settings: Settings
    session_factory: sessionmaker[Session]
    git: GitClient
    storage: RepositoryStorage
    index_store: RepositoryIndexStore
    embeddings: EmbeddingProvider
    rerankers: RerankerRegistry
    # Set when the worker is shutting down; long-running handlers check it.
    cancel_event: threading.Event = field(default_factory=threading.Event)


JobHandler = Callable[[JobContext, JobPayload], None]


def run_registered_job(
    name: str, payload: JobPayload, context: JobContext, handlers: Mapping[str, JobHandler]
) -> None:
    """Execute one job. Errors are logged, never raised into the worker loop."""
    handler = handlers[name]
    try:
        handler(context, payload)
    except Exception:
        logger.exception("background job crashed", extra={"job_name": name, "payload": payload})


class JobQueue(ABC):
    def __init__(self, context: JobContext, handlers: Mapping[str, JobHandler]) -> None:
        self.context = context
        self.handlers = handlers

    def enqueue(self, name: str, payload: JobPayload) -> None:
        """Schedule a job. Call only after the job's database row is committed."""
        if name not in self.handlers:
            raise ValueError(f"Unknown job: {name}")
        logger.info("job enqueued", extra={"job_name": name, "payload": payload})
        self._submit(name, payload)

    @abstractmethod
    def _submit(self, name: str, payload: JobPayload) -> None: ...

    def shutdown(self) -> None:
        """Stop accepting work and ask running jobs to stop."""
        self.context.cancel_event.set()

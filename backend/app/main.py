"""FastAPI application factory and ASGI entrypoint (`uvicorn app.main:app`)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import REQUEST_ID_HEADER, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine, get_session_factory
from app.ingestion.git import GitClient
from app.ingestion.indexer import recover_interrupted_jobs
from app.ingestion.storage import RepositoryStorage
from app.jobs.base import JobContext, JobQueue
from app.jobs.registry import build_job_queue
from app.retrieval.embeddings import create_embedding_provider
from app.retrieval.index_store import RepositoryIndexStore
from app.retrieval.rerankers import create_reranker_registry

logger = logging.getLogger(__name__)


def build_job_context(settings: Settings) -> JobContext:
    return JobContext(
        settings=settings,
        session_factory=get_session_factory(),
        git=GitClient(
            remote_timeout=settings.git_remote_timeout_seconds,
            clone_timeout=settings.git_clone_timeout_seconds,
        ),
        storage=RepositoryStorage(settings.repository_storage_dir),
        index_store=RepositoryIndexStore(settings.index_storage_dir),
        embeddings=create_embedding_provider(settings),
        rerankers=create_reranker_registry(settings),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("application startup", extra={"environment": settings.app_env})
    if app.state.recover_jobs_on_startup:
        try:
            await run_in_threadpool(recover_interrupted_jobs, app.state.job_context)
        except Exception:
            # Usually means the database is down; readiness checks will report it.
            logger.exception("could not recover interrupted jobs")
    yield
    await run_in_threadpool(app.state.job_queue.shutdown)
    dispose_engine()
    logger.info("application shutdown")


def create_app(
    settings: Settings | None = None,
    *,
    job_context: JobContext | None = None,
    job_queue: JobQueue | None = None,
) -> FastAPI:
    """Build the application.

    Tests pass their own `job_context` / `job_queue` (fake git, inline jobs);
    in normal runs both are built from settings.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="AI-powered codebase intelligence and review platform.",
        debug=settings.debug,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.job_context = job_context or build_job_context(settings)
    app.state.job_queue = job_queue or build_job_queue(settings, app.state.job_context)
    # Only the default in-process queue owns its jobs, so only it recovers them.
    app.state.recover_jobs_on_startup = job_queue is None

    # Middleware added last runs first: CORS wraps the request-context middleware,
    # so even generated 500 responses carry CORS headers.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()

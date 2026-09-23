"""Shared pytest fixtures.

By default tests run against an in-memory SQLite database, so `pytest` works
without a running database server. Set TEST_DATABASE_URL to run the same suite against PostgreSQL
(use a disposable database: tables are dropped after every test).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.session import get_db
from app.ingestion.storage import RepositoryStorage
from app.jobs.base import JobContext
from app.jobs.queues import InlineJobQueue
from app.jobs.registry import JOB_HANDLERS
from app.main import create_app
from app.models import Base
from app.retrieval.embeddings import HashingEmbeddingProvider
from app.retrieval.index_store import RepositoryIndexStore
from app.retrieval.rerankers import RerankerRegistry
from tests.fakes import FakeGitClient, KeywordReranker

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")
FRONTEND_ORIGIN = "http://localhost:3000"


def _create_test_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)

    # One shared in-memory connection, usable from TestClient's worker threads.
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    test_engine = _create_test_engine(TEST_DATABASE_URL)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session for arranging test data directly in the database."""
    with session_factory() as session:
        yield session


@pytest.fixture
def local_repos_root(tmp_path: Path) -> Path:
    """The only directory local repositories may be added from in tests."""
    root = tmp_path / "local-repos"
    root.mkdir()
    return root


@pytest.fixture
def settings(tmp_path: Path, local_repos_root: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        database_url=TEST_DATABASE_URL,
        log_level="WARNING",
        log_format="console",
        cors_origins=[FRONTEND_ORIGIN],
        repository_storage_dir=tmp_path / "storage",
        index_storage_dir=tmp_path / "indexes",
        embedding_cache_dir=tmp_path / "models",
        local_repository_roots=[local_repos_root],
        job_backend="inline",
        # Tests never download a model: hashed vectors are deterministic and offline.
        embedding_provider="hashing",
    )


@pytest.fixture
def fake_git() -> FakeGitClient:
    return FakeGitClient()


@pytest.fixture
def job_context(
    settings: Settings, session_factory: sessionmaker[Session], fake_git: FakeGitClient
) -> JobContext:
    return JobContext(
        settings=settings,
        session_factory=session_factory,
        git=fake_git,
        storage=RepositoryStorage(settings.repository_storage_dir),
        index_store=RepositoryIndexStore(settings.index_storage_dir),
        embeddings=HashingEmbeddingProvider(),
        rerankers=RerankerRegistry({KeywordReranker.name: KeywordReranker()}),
    )


@pytest.fixture
def app(
    settings: Settings, session_factory: sessionmaker[Session], job_context: JobContext
) -> FastAPI:
    # Jobs run inline, so "start indexing" completes before the response returns.
    application = create_app(
        settings, job_context=job_context, job_queue=InlineJobQueue(job_context, JOB_HANDLERS)
    )

    def _get_test_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = _get_test_db
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client

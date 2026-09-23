"""Database engine and session management.

The engine is created lazily on first use, so importing the application (for
example in tests or Alembic) never opens a database connection by itself.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    settings = get_settings()
    options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if make_url(database_url).get_backend_name() == "postgresql":
        options["pool_size"] = settings.database_pool_size
        options["max_overflow"] = settings.database_max_overflow
    return create_engine(database_url, **options)


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return build_engine(settings.database_url, echo=settings.database_echo)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    # expire_on_commit=False lets services return ORM objects after committing.
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields one session per request."""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()

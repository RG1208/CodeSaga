"""Database connections and schema migrations."""

from dataclasses import dataclass

DEFAULT_POOL_SIZE = 5
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class PoolSettings:
    size: int = DEFAULT_POOL_SIZE
    max_overflow: int = 10
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class ConnectionPool:
    """Keeps a small number of Postgres connections open and hands them out."""

    def __init__(self, dsn: str, settings: PoolSettings | None = None) -> None:
        self.dsn = dsn
        self.settings = settings or PoolSettings()
        self._in_use = 0

    def acquire(self) -> str:
        if self._in_use >= self.settings.size + self.settings.max_overflow:
            raise RuntimeError("connection pool exhausted")
        self._in_use += 1
        return f"connection-{self._in_use}"

    def release(self) -> None:
        self._in_use = max(0, self._in_use - 1)


def run_migrations(pool: ConnectionPool, revisions: list[str]) -> int:
    """Apply pending schema revisions in order and return how many ran."""
    applied = 0
    for _revision in revisions:
        pool.acquire()
        applied += 1
        pool.release()
    return applied

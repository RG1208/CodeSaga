"""Application configuration.

All settings are read from environment variables (or a `.env` file) and
validated by Pydantic, so a misconfigured deployment fails fast at startup
instead of misbehaving later.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _split_comma_separated(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _absolute_path(value: Path) -> Path:
    """Expand `~` and anchor relative paths at the repository root."""
    path = value.expanduser()
    return (path if path.is_absolute() else REPO_ROOT / path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # The repo-root .env is the main config file; a backend/.env (if present)
        # overrides it. Real environment variables win over both.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CodeSage"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    log_level: LogLevel = "INFO"
    log_format: Literal["json", "console"] = "json"

    database_url: str = "postgresql+psycopg://codesage:codesage@localhost:5432/codesage"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    # Accepts a comma-separated string, e.g. "http://localhost:3000,https://app.example.com".
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # --- Repository ingestion -------------------------------------------------
    # Where cloned repositories are stored. Keep it OUTSIDE backend/, otherwise
    # `uvicorn --reload` restarts the server whenever a clone writes .py files.
    repository_storage_dir: Path = REPO_ROOT / "data" / "repositories"
    # Local filesystem repositories are only ever accepted when APP_ENV is
    # development or test, and only from inside these directories.
    allow_local_repositories: bool = True
    local_repository_roots: Annotated[list[Path], NoDecode] = Field(
        default_factory=lambda: [Path.home()]
    )
    git_remote_timeout_seconds: int = Field(default=30, ge=1)
    git_clone_timeout_seconds: int = Field(default=600, ge=1)
    max_repository_size_mb: int = Field(default=1024, ge=1)
    max_repository_files: int = Field(default=100_000, ge=1)
    # Files larger than this are counted but not added to the file index.
    max_indexed_file_size_kb: int = Field(default=1024, ge=1)
    # Source files larger than this are indexed but not parsed into symbols
    # (typically generated or bundled code).
    max_parsed_file_size_kb: int = Field(default=512, ge=1)

    # --- Retrieval (Phase 4) --------------------------------------------------
    # Build BM25 + dense indexes as the last stage of indexing.
    retrieval_enabled: bool = True
    index_storage_dir: Path = REPO_ROOT / "data" / "indexes"
    # Chunking: prefer whole functions/classes; only split what is larger than this.
    chunk_max_lines: int = Field(default=60, ge=5)
    chunk_max_chars: int = Field(default=4000, ge=200)
    chunk_overlap_lines: int = Field(default=8, ge=0)
    chunk_min_lines: int = Field(default=2, ge=1)

    bm25_k1: float = Field(default=1.2, ge=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)

    dense_retrieval_enabled: bool = True
    # "fastembed": local BGE models through ONNX Runtime.
    # "hashing": deterministic offline vectors (tests, or machines without the model).
    embedding_provider: Literal["fastembed", "hashing"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = Field(default=16, ge=1)
    embedding_threads: int | None = None
    # BGE v1.5 recommends this instruction on the query side only.
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    # Text beyond the model's window is ignored anyway; truncating keeps indexing quick.
    embedding_max_chars: int = Field(default=2000, ge=200)
    embedding_cache_dir: Path = REPO_ROOT / "data" / "models"
    max_embedded_chunks: int = Field(default=20000, ge=1)
    vector_store: Literal["faiss"] = "faiss"

    hybrid_fusion: Literal["rrf", "weighted"] = "rrf"
    hybrid_bm25_weight: float = Field(default=0.5, ge=0)
    hybrid_dense_weight: float = Field(default=0.5, ge=0)
    hybrid_rrf_k: int = Field(default=60, ge=1)
    hybrid_candidates: int = Field(default=50, ge=1, le=500)

    reranker_provider: Literal["cross_encoder", "none"] = "cross_encoder"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = Field(default=20, ge=1, le=200)
    rerank_max_chars: int = Field(default=1200, ge=200)

    # Store every search for later research evaluation (can be overridden per request).
    retrieval_logging_enabled: bool = True

    # --- Background jobs ------------------------------------------------------
    # "thread": run jobs in a thread pool inside the API process.
    # "inline": run jobs synchronously during the request (tests/debugging only).
    job_backend: Literal["thread", "inline"] = "thread"
    job_workers: int = Field(default=2, ge=1)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        origins = _split_comma_separated(value)
        if isinstance(origins, list):
            return [str(origin).rstrip("/") for origin in origins]
        return origins

    @field_validator("local_repository_roots", mode="before")
    @classmethod
    def _split_local_roots(cls, value: object) -> object:
        return _split_comma_separated(value)

    @field_validator("repository_storage_dir", "index_storage_dir", "embedding_cache_dir")
    @classmethod
    def _resolve_storage_dir(cls, value: Path) -> Path:
        return _absolute_path(value)

    @field_validator("local_repository_roots")
    @classmethod
    def _resolve_local_roots(cls, value: list[Path]) -> list[Path]:
        return [_absolute_path(path) for path in value]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def local_repositories_enabled(self) -> bool:
        return self.allow_local_repositories and self.app_env in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (created once, then cached)."""
    return Settings()

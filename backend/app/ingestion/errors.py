"""Domain errors raised by the ingestion package.

They carry a stable machine-readable `code` and a user-safe `message`. They are
deliberately not HTTP errors: the service layer maps them to HTTP responses, and
the background indexer stores the message on the failed job.
"""

from enum import StrEnum


class IngestionError(Exception):
    code: str = "ingestion_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code


class InvalidRepositorySourceError(IngestionError):
    """The URL, branch name or local path supplied by the user is not acceptable."""

    code = "invalid_repository_source"


class UnsafePathError(IngestionError):
    """A filesystem path would escape the directory it must stay inside."""

    code = "unsafe_path"


class RepositoryLimitExceededError(IngestionError):
    """The repository is larger than the configured size or file-count limits."""

    code = "repository_too_large"


class IngestionCancelledError(IngestionError):
    """Work stopped because the server is shutting down."""

    code = "indexing_interrupted"

    def __init__(self) -> None:
        super().__init__(
            "Indexing was interrupted because the server stopped. Start indexing again."
        )


class GitErrorKind(StrEnum):
    NOT_FOUND = "repository_not_found"
    BRANCH_NOT_FOUND = "branch_not_found"
    EMPTY_REPOSITORY = "empty_repository"
    NETWORK = "network_error"
    TIMEOUT = "git_timeout"
    UNAVAILABLE = "git_unavailable"
    FAILED = "git_failed"


class GitCommandError(IngestionError):
    def __init__(self, message: str, kind: GitErrorKind) -> None:
        super().__init__(message, code=kind.value)
        self.kind = kind

"""Errors raised by the retrieval layer (mapped to HTTP responses by the service)."""


class RetrievalError(Exception):
    code = "retrieval_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code


class IndexUnavailableError(RetrievalError):
    """No usable search index for this repository (not built, or out of date)."""

    code = "index_unavailable"


class EmbeddingUnavailableError(RetrievalError):
    """The embedding model could not be loaded (e.g. it has never been downloaded)."""

    code = "embedding_unavailable"


class RerankerUnavailableError(RetrievalError):
    code = "reranker_unavailable"

"""Embedding providers behind the `EmbeddingProvider` interface."""

import numpy as np
import pytest

from app.core.config import Settings
from app.retrieval.embeddings import (
    FastEmbedProvider,
    HashingEmbeddingProvider,
    create_embedding_provider,
)
from app.retrieval.errors import EmbeddingUnavailableError


@pytest.fixture
def provider() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider(dimension=64)


def test_vectors_are_normalised_and_shaped(provider: HashingEmbeddingProvider) -> None:
    vectors = provider.embed_documents(["def hash_password(): ...", "class LruCache: ..."])

    assert vectors.shape == (2, 64)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_deterministic(provider: HashingEmbeddingProvider) -> None:
    first = provider.embed_documents(["refund a payment"])
    second = HashingEmbeddingProvider(dimension=64).embed_documents(["refund a payment"])

    assert np.array_equal(first, second)


def test_similar_text_scores_higher(provider: HashingEmbeddingProvider) -> None:
    documents = provider.embed_documents(
        ["def refund_payment(charge): ...", "def send_email(recipient): ..."]
    )
    query = provider.embed_query("refund payment")

    similarities = documents @ query
    assert similarities[0] > similarities[1]


def test_empty_input(provider: HashingEmbeddingProvider) -> None:
    assert provider.embed_documents([]).shape == (0, 64)


def test_progress_callback(provider: HashingEmbeddingProvider) -> None:
    seen: list[tuple[int, int]] = []

    provider.embed_documents(
        ["a", "b", "c"], on_progress=lambda done, total: seen.append((done, total))
    )

    assert seen[-1] == (3, 3)


def test_describe(provider: HashingEmbeddingProvider) -> None:
    assert provider.describe() == {"provider": "hashing", "model": "hashing-v1", "dimension": 64}


def test_factory_follows_configuration() -> None:
    hashing = create_embedding_provider(Settings(_env_file=None, embedding_provider="hashing"))
    fastembed = create_embedding_provider(
        Settings(
            _env_file=None, embedding_provider="fastembed", embedding_model="BAAI/bge-small-en-v1.5"
        )
    )

    assert isinstance(hashing, HashingEmbeddingProvider)
    assert isinstance(fastembed, FastEmbedProvider)
    assert fastembed.model_id == "BAAI/bge-small-en-v1.5"  # no model is loaded yet


def test_unknown_model_reports_unavailable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = FastEmbedProvider(
        Settings(
            _env_file=None,
            embedding_provider="fastembed",
            embedding_model="not-a-real/model",
            embedding_cache_dir=tmp_path,
        )
    )

    with pytest.raises(EmbeddingUnavailableError, match="not-a-real/model"):
        provider.embed_documents(["text"])

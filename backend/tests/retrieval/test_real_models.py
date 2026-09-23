"""Opt-in checks against the real BGE embedding model and cross-encoder reranker.

Skipped by default: the models are ~100 MB of downloads and take seconds to load, so
CI and everyday `pytest` runs use the deterministic hashing provider instead. Run these
before changing the embedding or reranking configuration:

    REAL_MODEL_TESTS=1 .venv/bin/pytest tests/retrieval/test_real_models.py -v

They are the only tests that prove semantic retrieval actually finds code the lexical
index cannot: the queries here deliberately share almost no words with the source.
"""

import os

import pytest

from app.core.config import Settings
from app.retrieval.embeddings import EmbeddingUnavailableError, create_embedding_provider
from app.retrieval.engine import RetrievalStrategy, SearchOptions
from app.retrieval.rerankers import create_reranker_registry
from research.metrics import CaseOutcome, EvaluationCase, summarise, unique_files
from tests.retrieval.helpers import build_fixture_index

pytestmark = pytest.mark.skipif(
    not os.getenv("REAL_MODEL_TESTS"),
    reason="set REAL_MODEL_TESTS=1 to download and run the real models",
)

# Paraphrases: the wording is what a user would type, not what the code says.
PARAPHRASES: list[tuple[str, str]] = [
    ("where do we turn a plaintext secret into something safe to store", "app/auth/passwords.py"),
    ("how do we know a signed session string has not been tampered with", "app/auth/tokens.py"),
    ("give the money back to the buyer", "app/billing/refunds.py"),
    ("take money from a customer's card", "app/billing/payments.py"),
    ("tell the customer by mail that something happened", "app/notifications/email.py"),
    ("stop a noisy client from hammering the service", "app/middleware/rate_limit.py"),
    ("throw away the entry nobody has touched for the longest time", "app/storage/cache.py"),
    ("how many connections do we keep open to postgres", "app/storage/database.py"),
    ("move a late ticket up to someone more senior", "app/tickets/escalation.py"),
]


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("real-models")
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        index_storage_dir=root / "indexes",
        # The configured cache (data/models at the repo root), so a second run — and the
        # running backend — reuse the same download.
        embedding_cache_dir=Settings(_env_file=None).embedding_cache_dir,  # type: ignore[call-arg]
        embedding_provider="fastembed",
    )


@pytest.fixture(scope="module")
def embeddings(settings: Settings):  # type: ignore[no-untyped-def]
    provider = create_embedding_provider(settings)
    try:
        provider.embed_query("warm up the model")
    except EmbeddingUnavailableError as exc:  # pragma: no cover - depends on the network
        pytest.skip(f"embedding model unavailable: {exc.message}")
    return provider


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory, settings: Settings, embeddings):  # type: ignore[no-untyped-def]
    return build_fixture_index(
        tmp_path_factory.mktemp("index"), embeddings=embeddings, settings=settings
    )


def test_the_configured_model_is_the_one_that_gets_used(embeddings, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    described = embeddings.describe()

    assert embeddings.model_id == settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert described["provider"] == "fastembed"
    assert described["dimension"] == 384
    assert len(embeddings.embed_query("hash a password")) == 384


def test_dense_retrieval_answers_paraphrased_questions(fixture_index, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    outcomes = []
    for query, expected in PARAPHRASES:
        outcome = fixture_index.engine().search(
            query,
            strategy=RetrievalStrategy.DENSE,
            top_k=5,
            options=SearchOptions.from_settings(settings),
        )
        outcomes.append(
            CaseOutcome(
                case=EvaluationCase(query=query, relevant_files=frozenset({expected})),
                retrieved_files=unique_files(
                    [fixture_index.file_of(item.chunk_id) for item in outcome.items]
                ),
                latency_ms=outcome.timings["total_ms"],
            )
        )

    summary = summarise(outcomes, k=5)
    print(f"\ndense on paraphrases: {summary}")
    misses = [outcome.case.query for outcome in outcomes if outcome.metrics["hit@5"] == 0]
    assert summary["hit@5"] >= 0.75, misses


def test_dense_beats_lexical_on_paraphrases(fixture_index, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    """The reason for embeddings at all: wording the code never uses."""

    def score(strategy: RetrievalStrategy) -> float:
        outcomes = [
            CaseOutcome(
                case=EvaluationCase(query=query, relevant_files=frozenset({expected})),
                retrieved_files=unique_files(
                    [
                        fixture_index.file_of(item.chunk_id)
                        for item in fixture_index.engine()
                        .search(
                            query,
                            strategy=strategy,
                            top_k=5,
                            options=SearchOptions.from_settings(settings),
                        )
                        .items
                    ]
                ),
            )
            for query, expected in PARAPHRASES
        ]
        return summarise(outcomes, k=5)["hit@5"]

    bm25, dense, hybrid = (
        score(RetrievalStrategy.BM25),
        score(RetrievalStrategy.DENSE),
        score(RetrievalStrategy.HYBRID),
    )
    print(f"\nhit@5 — bm25: {bm25}  dense: {dense}  hybrid: {hybrid}")
    assert dense > bm25
    assert hybrid >= bm25


def test_cross_encoder_reranks_hybrid_candidates(fixture_index, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    registry = create_reranker_registry(settings)
    if not registry.names:  # pragma: no cover - depends on the install
        pytest.skip("no reranker configured")
    reranker = registry.get(registry.default)

    query = "how do we know a signed session string has not been tampered with"
    options = SearchOptions.from_settings(settings)
    hybrid = fixture_index.engine().search(
        query, strategy=RetrievalStrategy.HYBRID, top_k=5, options=options
    )
    reranked = fixture_index.engine().search(
        query,
        strategy=RetrievalStrategy.HYBRID_RERANK,
        top_k=5,
        options=options,
        reranker=reranker,
    )

    print(f"\nrerank took {reranked.timings['rerank_ms']:.0f} ms for {options.rerank_candidates}")
    assert reranked.reranker == reranker.name
    assert fixture_index.file_of(reranked.items[0].chunk_id) == "app/auth/tokens.py"
    assert {item.chunk_id for item in reranked.items} - {
        item.chunk_id for item in hybrid.items
    } or ([item.chunk_id for item in reranked.items] != [item.chunk_id for item in hybrid.items]), (
        "reranking changed neither the members nor the order of the top 5"
    )

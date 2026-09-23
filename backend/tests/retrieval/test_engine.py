"""The four retrieval strategies, measured on the deterministic fixture repository.

Embeddings are the offline hashing provider, so these numbers are reproducible and no
model is downloaded. Real BGE models are exercised in `test_real_models.py`.
"""

from pathlib import Path

import pytest

from app.retrieval.engine import (
    BM25Retriever,
    DenseRetriever,
    HybridRetriever,
    RerankingRetriever,
    RetrievalStrategy,
    SearchOptions,
)
from app.retrieval.errors import IndexUnavailableError
from app.retrieval.fusion import FusionConfig
from research.metrics import CaseOutcome, EvaluationCase, summarise, unique_files
from tests.fakes import KeywordReranker
from tests.retrieval.helpers import build_fixture_index

# query → the file a good answer must come from
QUERIES: list[tuple[str, str]] = [
    ("hash a user password securely", "app/auth/passwords.py"),
    ("verify a json web token signature", "app/auth/tokens.py"),
    ("refund a customer payment", "app/billing/refunds.py"),
    ("charge a credit card", "app/billing/payments.py"),
    ("send an email notification", "app/notifications/email.py"),
    ("send a text message", "app/notifications/sms.py"),
    ("limit how many requests a client can make", "app/middleware/rate_limit.py"),
    ("evict least recently used cache entries", "app/storage/cache.py"),
    ("database connection pool size", "app/storage/database.py"),
    ("assign a ticket to an agent", "app/tickets/service.py"),
    ("escalate an overdue ticket to a manager", "app/tickets/escalation.py"),
    ("login form component", "web/src/components/LoginForm.tsx"),
]


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    return build_fixture_index(tmp_path_factory.mktemp("retrieval"))


def run(fixture_index, strategy: RetrievalStrategy, query: str, top_k: int = 5, **overrides):  # type: ignore[no-untyped-def]
    options = SearchOptions.from_settings(fixture_index.settings, **overrides)
    reranker = KeywordReranker() if strategy is RetrievalStrategy.HYBRID_RERANK else None
    return fixture_index.engine().search(
        query, strategy=strategy, top_k=top_k, options=options, reranker=reranker
    )


def files_for(fixture_index, outcome) -> list[str]:  # type: ignore[no-untyped-def]
    return unique_files([fixture_index.file_of(item.chunk_id) for item in outcome.items])


@pytest.mark.parametrize("strategy", list(RetrievalStrategy))
def test_every_strategy_retrieves_the_relevant_file(fixture_index, strategy) -> None:  # type: ignore[no-untyped-def]
    outcomes = []
    for query, expected in QUERIES:
        outcome = run(fixture_index, strategy, query)
        outcomes.append(
            CaseOutcome(
                case=EvaluationCase(query=query, relevant_files=frozenset({expected})),
                retrieved_files=files_for(fixture_index, outcome),
                latency_ms=outcome.timings["total_ms"],
            )
        )

    summary = summarise(outcomes, k=5)
    assert summary["recall@5"] == 1.0, [
        (outcome.case.query, outcome.retrieved_files)
        for outcome in outcomes
        if outcome.metrics["recall@5"] < 1
    ]
    assert summary["mrr"] >= 0.9


@pytest.mark.parametrize("strategy", list(RetrievalStrategy))
def test_results_are_ranked_and_scored(fixture_index, strategy) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, strategy, "refund a customer payment", top_k=4)

    assert [item.rank for item in outcome.items] == [1, 2, 3, 4]
    assert all(item.chunk_id for item in outcome.items)
    scores = [item.score for item in outcome.items]
    assert scores == sorted(scores, reverse=True)
    assert outcome.strategy is strategy
    assert outcome.timings["total_ms"] >= 0


def test_top_k_is_respected(fixture_index) -> None:  # type: ignore[no-untyped-def]
    for top_k in (1, 3, 7):
        assert (
            len(run(fixture_index, RetrievalStrategy.HYBRID, "password", top_k=top_k).items)
            == top_k
        )


def test_bm25_reports_lexical_scores(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.BM25, "pbkdf2 salted hash")

    assert fixture_index.file_of(outcome.items[0].chunk_id) == "app/auth/passwords.py"
    assert set(outcome.items[0].components) == {"bm25", "bm25_rank"}
    assert "bm25_ms" in outcome.timings and "tokenize_ms" in outcome.timings


def test_dense_reports_similarity_scores(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.DENSE, "least recently used eviction")

    assert set(outcome.items[0].components) == {"dense", "dense_rank"}
    assert 0.0 <= outcome.items[0].components["dense"] <= 1.0
    assert "embed_query_ms" in outcome.timings and "dense_ms" in outcome.timings


def test_hybrid_combines_both_retrievers(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.HYBRID, "refund a customer payment")

    components = {key for item in outcome.items for key in item.components}
    assert {"bm25", "dense"} & components
    assert "fusion_ms" in outcome.timings
    assert outcome.fusion is not None and outcome.fusion.method == "rrf"


def test_hybrid_finds_what_one_retriever_alone_misses(fixture_index) -> None:  # type: ignore[no-untyped-def]
    query = "evict least recently used cache entries"
    hybrid = files_for(fixture_index, run(fixture_index, RetrievalStrategy.HYBRID, query, top_k=3))

    assert "app/storage/cache.py" in hybrid


def test_fusion_options_change_the_ranking(fixture_index) -> None:  # type: ignore[no-untyped-def]
    query = "password"
    lexical_heavy = run(
        fixture_index,
        RetrievalStrategy.HYBRID,
        query,
        fusion_method="weighted",
        bm25_weight=1.0,
        dense_weight=0.0,
    )
    dense_heavy = run(
        fixture_index,
        RetrievalStrategy.HYBRID,
        query,
        fusion_method="weighted",
        bm25_weight=0.0,
        dense_weight=1.0,
    )

    assert lexical_heavy.fusion is not None and lexical_heavy.fusion.bm25_weight == 1.0
    bm25_only = run(fixture_index, RetrievalStrategy.BM25, query)
    dense_only = run(fixture_index, RetrievalStrategy.DENSE, query)
    assert lexical_heavy.items[0].chunk_id == bm25_only.items[0].chunk_id
    assert dense_heavy.items[0].chunk_id == dense_only.items[0].chunk_id


def test_reranking_rescores_the_candidates(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.HYBRID_RERANK, "refund a customer payment")

    assert outcome.reranker == "keyword"
    top = outcome.items[0]
    assert "rerank" in top.components  # final score comes from the reranker
    assert top.score == top.components["rerank"]
    assert "first_stage_rank" in top.components  # the hybrid position is kept
    assert "rerank_ms" in outcome.timings


def test_reranker_only_sees_the_configured_number_of_candidates(fixture_index) -> None:  # type: ignore[no-untyped-def]
    seen: list[int] = []

    class CountingReranker(KeywordReranker):
        def rerank(self, query, documents):  # type: ignore[no-untyped-def]
            seen.append(len(documents))
            return super().rerank(query, documents)

    options = SearchOptions.from_settings(fixture_index.settings, rerank_candidates=6)
    fixture_index.engine().search(
        "password",
        strategy=RetrievalStrategy.HYBRID_RERANK,
        top_k=3,
        options=options,
        reranker=CountingReranker(),
    )

    assert seen == [6]


def test_strategies_can_be_used_directly(fixture_index) -> None:  # type: ignore[no-untyped-def]
    """Each strategy is a Retriever, so research code can call them without the engine."""
    options = SearchOptions(fusion=FusionConfig(), candidates=20, rerank_candidates=5)
    bm25 = BM25Retriever(fixture_index.index)
    dense = DenseRetriever(fixture_index.index, fixture_index.embeddings)
    hybrid = HybridRetriever(bm25, dense, options)
    reranked = RerankingRetriever(hybrid, KeywordReranker(), fixture_index.documents, options)

    for retriever in (bm25, dense, hybrid, reranked):
        results = retriever.retrieve("refund a payment", 3)
        assert len(results) == 3
        assert [item.rank for item in results] == [1, 2, 3]


def test_metadata_is_preserved_end_to_end(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.BM25, "verify a json web token signature")
    chunk = fixture_index.by_id()[outcome.items[0].chunk_id]
    assert chunk.file_path == "app/auth/tokens.py"
    assert chunk.language == "python"
    assert chunk.symbol_name == "decode_token"
    assert chunk.symbol_type == "function"
    assert chunk.qualified_name == "decode_token"
    assert chunk.parent_symbol is None
    assert chunk.start_line < chunk.end_line
    assert chunk.chunk_type == "symbol"
    # The line range points at the real source lines.
    lines = (
        (Path(__file__).resolve().parents[1] / "fixtures/retrieval/support_desk/app/auth/tokens.py")
        .read_text()
        .splitlines()
    )
    assert lines[chunk.start_line - 1].startswith("def decode_token")
    assert chunk.content.splitlines() == lines[chunk.start_line - 1 : chunk.end_line]


def test_a_class_that_fits_stays_one_chunk(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(fixture_index, RetrievalStrategy.BM25, "assign a ticket to an agent")
    chunk = fixture_index.by_id()[outcome.items[0].chunk_id]

    assert chunk.file_path == "app/tickets/service.py"
    assert chunk.qualified_name == "TicketService"
    assert chunk.symbol_type == "class"
    assert "def assign_ticket" in chunk.content


def test_methods_of_a_split_class_keep_their_parent(fixture_index) -> None:  # type: ignore[no-untyped-def]
    """EscalationPolicy is longer than one chunk, so its methods are chunked separately."""
    outcome = run(fixture_index, RetrievalStrategy.BM25, "escalate an overdue ticket to a manager")
    chunk = fixture_index.by_id()[outcome.items[0].chunk_id]

    assert chunk.file_path == "app/tickets/escalation.py"
    assert chunk.qualified_name == "EscalationPolicy.escalate_to_manager"
    assert chunk.parent_symbol == "EscalationPolicy"
    assert chunk.symbol_type == "method"
    assert chunk.chunk_type == "symbol"

    header = next(
        candidate
        for candidate in fixture_index.chunks
        if candidate.chunk_type == "symbol_header" and candidate.symbol_name == "EscalationPolicy"
    )
    assert header.symbol_type == "class"
    assert "class EscalationPolicy" in header.content


def test_documentation_is_retrievable(fixture_index) -> None:  # type: ignore[no-untyped-def]
    outcome = run(
        fixture_index, RetrievalStrategy.BM25, "architecture of the support desk", top_k=3
    )
    files = files_for(fixture_index, outcome)

    assert any(path.endswith(".md") for path in files)
    markdown = next(
        fixture_index.by_id()[item.chunk_id]
        for item in outcome.items
        if fixture_index.file_of(item.chunk_id).endswith(".md")
    )
    assert markdown.chunk_type == "section"
    assert markdown.symbol_name


def test_nonsense_query_returns_nothing_rather_than_noise(fixture_index) -> None:  # type: ignore[no-untyped-def]
    assert run(fixture_index, RetrievalStrategy.BM25, "kubernetes helm istio sidecar").items == []


def test_dense_strategy_without_a_dense_index(tmp_path: Path) -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        embedding_provider="hashing",
        index_storage_dir=tmp_path / "indexes",
        dense_retrieval_enabled=False,
    )
    fixture = build_fixture_index(tmp_path, settings=settings)

    assert fixture.summary["dense"]["status"] == "disabled"
    with pytest.raises(IndexUnavailableError) as caught:
        fixture.engine().search(
            "password",
            strategy=RetrievalStrategy.DENSE,
            top_k=5,
            options=SearchOptions.from_settings(settings),
        )
    assert caught.value.code == "dense_index_unavailable"
    # BM25 still answers.
    assert (
        fixture.engine()
        .search(
            "password",
            strategy=RetrievalStrategy.BM25,
            top_k=5,
            options=SearchOptions.from_settings(settings),
        )
        .items
    )

"""BM25: scoring behaviour, persistence and edge cases."""

from pathlib import Path

import pytest

from app.retrieval.bm25 import BM25Index, BM25Params
from app.retrieval.tokenizer import tokenize

DOCUMENTS = {
    "passwords": "def hash_password(password): return pbkdf2_hmac(password, salt)",
    "refunds": "def refund_payment(charge): return gateway.refund(charge)",
    "cache": "class LruCache: def put(self, key, value): evict least recently used",
    "mixed": "password refund cache",
}


@pytest.fixture
def index() -> BM25Index:
    return BM25Index.build([tokenize(text) for text in DOCUMENTS.values()])


def names(hits: list[tuple[int, float]]) -> list[str]:
    keys = list(DOCUMENTS)
    return [keys[position] for position, _ in hits]


def test_exact_term_match_ranks_first(index: BM25Index) -> None:
    assert names(index.search(tokenize("hash password"), 3))[0] == "passwords"
    assert names(index.search(tokenize("refund a payment"), 3))[0] == "refunds"
    assert names(index.search(tokenize("least recently used"), 3))[0] == "cache"


def test_term_frequency_and_idf(index: BM25Index) -> None:
    # "password" occurs three times in the passwords document and once in "mixed".
    assert names(index.search(tokenize("password"), 2)) == ["passwords", "mixed"]
    # "pbkdf2" occurs in one document only, so nothing else can match it.
    assert names(index.search(tokenize("pbkdf2"), 5)) == ["passwords"]


def test_length_normalisation_prefers_the_shorter_document(index: BM25Index) -> None:
    # Both documents contain "cache"; the short one wins because the term is denser.
    assert names(index.search(tokenize("cache"), 2))[0] == "mixed"


def test_scores_are_positive_and_sorted(index: BM25Index) -> None:
    hits = index.search(tokenize("password refund cache"), 4)

    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_unknown_and_empty_queries(index: BM25Index) -> None:
    assert index.search(tokenize("kubernetes helm chart"), 5) == []
    assert index.search([], 5) == []


def test_top_k_is_respected(index: BM25Index) -> None:
    assert len(index.search(tokenize("password refund cache"), 2)) == 2


def test_only_matching_documents_are_returned(index: BM25Index) -> None:
    assert len(index.search(tokenize("pbkdf2"), 10)) == 1


def test_k1_controls_how_much_repetition_helps() -> None:
    """k1 is the term-frequency saturation point: low k1 means "seen once is enough"."""
    documents = [tokenize("cache cache cache cache other"), tokenize("cache")]

    def score_ratio(k1: float) -> float:
        hits = BM25Index.build(documents, BM25Params(k1=k1, b=0.0)).search(tokenize("cache"), 2)
        assert hits[0][0] == 0  # the document with four occurrences always ranks first
        return hits[0][1] / hits[1][1]

    assert score_ratio(0.1) < 1.1  # repetition barely counts
    assert score_ratio(8.0) > 2.5  # repetition counts a lot


def test_b_controls_length_normalisation() -> None:
    documents = [tokenize("cache " * 3 + "unrelated " * 30), tokenize("cache")]

    without = BM25Index.build(documents, BM25Params(b=0.0)).search(tokenize("cache"), 2)
    with_penalty = BM25Index.build(documents, BM25Params(b=1.0)).search(tokenize("cache"), 2)

    assert without[0][0] == 0  # b=0: the long document wins on term frequency
    assert with_penalty[0][0] == 1  # b=1: its length is penalised and the short one wins


def test_empty_corpus() -> None:
    index = BM25Index.build([])

    assert index.document_count == 0
    assert index.search(tokenize("anything"), 5) == []


def test_save_and_load_round_trip(index: BM25Index, tmp_path: Path) -> None:
    index.save(tmp_path)
    loaded = BM25Index.load(tmp_path)

    assert loaded.document_count == index.document_count
    assert loaded.term_count == index.term_count
    assert loaded.params == index.params
    assert loaded.average_length == pytest.approx(index.average_length)
    query = tokenize("hash password refund")
    assert loaded.search(query, 5) == index.search(query, 5)


def test_index_statistics(index: BM25Index) -> None:
    assert index.document_count == len(DOCUMENTS)
    assert index.term_count > 10
    assert index.average_length > 0

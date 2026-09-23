"""Fusion of the lexical and dense rankings."""

import pytest

from app.retrieval.fusion import FusionConfig, ScoredChunk, fuse

BM25 = [ScoredChunk("a", 12.0), ScoredChunk("b", 8.0), ScoredChunk("c", 2.0)]
DENSE = [ScoredChunk("c", 0.90), ScoredChunk("a", 0.60), ScoredChunk("d", 0.50)]


def order(config: FusionConfig) -> list[str]:
    return [item.chunk_id for item in fuse({"bm25": BM25, "dense": DENSE}, config)]


def test_rrf_uses_ranks_only() -> None:
    merged = fuse({"bm25": BM25, "dense": DENSE}, FusionConfig(method="rrf", rrf_k=60))

    # "a" is 1st and 2nd; "c" is 3rd and 1st. 1/61 + 1/62 beats 1/63 + 1/61.
    assert [item.chunk_id for item in merged] == ["a", "c", "b", "d"]
    assert merged[0].score == pytest.approx(0.5 / 61 + 0.5 / 62)
    assert [item.rank for item in merged] == [1, 2, 3, 4]


def test_rrf_k_controls_how_much_top_ranks_matter() -> None:
    assert order(FusionConfig(method="rrf", rrf_k=1))[0] == "a"
    assert order(FusionConfig(method="rrf", rrf_k=1000))[0] == "a"


def test_weighted_fusion_uses_normalised_scores() -> None:
    merged = fuse({"bm25": BM25, "dense": DENSE}, FusionConfig(method="weighted"))

    # bm25: a=1.0 b=0.6 c=0.0; dense: c=1.0 a=0.25 d=0.0 → a=0.625, c=0.5, b=0.3, d=0.0
    assert [item.chunk_id for item in merged] == ["a", "c", "b", "d"]
    assert merged[0].score == pytest.approx(0.625)


def test_weights_are_configurable() -> None:
    assert order(FusionConfig(method="weighted", bm25_weight=0.95, dense_weight=0.05)) == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert order(FusionConfig(method="weighted", bm25_weight=0.05, dense_weight=0.95))[0] == "c"


def test_component_scores_are_kept_for_every_result() -> None:
    merged = {
        item.chunk_id: item.components
        for item in fuse({"bm25": BM25, "dense": DENSE}, FusionConfig())
    }

    assert merged["a"] == {"bm25": 12.0, "bm25_rank": 1.0, "dense": 0.60, "dense_rank": 2.0}
    assert merged["d"] == {"dense": 0.50, "dense_rank": 3.0}  # dense-only hit


def test_single_list_and_empty_inputs() -> None:
    assert [item.chunk_id for item in fuse({"bm25": BM25}, FusionConfig())] == ["a", "b", "c"]
    assert fuse({}, FusionConfig()) == []
    assert fuse({"bm25": [], "dense": []}, FusionConfig()) == []


def test_identical_scores_break_ties_deterministically() -> None:
    tied = [ScoredChunk("z", 1.0), ScoredChunk("y", 1.0)]

    first = [item.chunk_id for item in fuse({"bm25": tied}, FusionConfig(method="weighted"))]
    second = [
        item.chunk_id
        for item in fuse({"bm25": list(reversed(tied))}, FusionConfig(method="weighted"))
    ]

    assert first == second == ["y", "z"]

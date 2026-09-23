"""Retrieval metrics used by the research benchmark."""

import math

from research.metrics import (
    CaseOutcome,
    EvaluationCase,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_case,
    summarise,
    unique_files,
)

RELEVANT = frozenset({"a.py", "b.py"})


def test_recall_counts_relevant_files_found() -> None:
    assert recall_at_k(["a.py", "x.py", "b.py"], RELEVANT, 3) == 1.0
    assert recall_at_k(["a.py", "x.py", "b.py"], RELEVANT, 2) == 0.5
    assert recall_at_k(["x.py"], RELEVANT, 5) == 0.0
    assert recall_at_k(["a.py"], frozenset(), 5) == 0.0


def test_precision_counts_relevant_results_returned() -> None:
    assert precision_at_k(["a.py", "x.py"], RELEVANT, 2) == 0.5
    assert precision_at_k(["a.py", "b.py"], RELEVANT, 2) == 1.0
    assert precision_at_k([], RELEVANT, 5) == 0.0


def test_hit_is_all_or_nothing() -> None:
    assert hit_at_k(["x.py", "b.py"], RELEVANT, 2) == 1.0
    assert hit_at_k(["x.py", "b.py"], RELEVANT, 1) == 0.0


def test_reciprocal_rank_rewards_early_hits() -> None:
    assert reciprocal_rank(["a.py", "x.py"], RELEVANT) == 1.0
    assert reciprocal_rank(["x.py", "a.py"], RELEVANT) == 0.5
    assert reciprocal_rank(["x.py", "y.py"], RELEVANT) == 0.0


def test_ndcg_prefers_relevant_results_at_the_top() -> None:
    assert ndcg_at_k(["a.py", "b.py"], RELEVANT, 2) == 1.0
    assert ndcg_at_k(["x.py", "y.py"], RELEVANT, 2) == 0.0
    early = ndcg_at_k(["a.py", "x.py", "y.py"], RELEVANT, 3)
    late = ndcg_at_k(["x.py", "y.py", "a.py"], RELEVANT, 3)
    assert early > late
    # One of two relevant files at rank 1: gain 1 of an ideal 1 + 1/log2(3).
    assert math.isclose(early, 1 / (1 + 1 / math.log2(3)))


def test_score_case_names_metrics_after_k() -> None:
    outcome = CaseOutcome(
        case=EvaluationCase(query="q", relevant_files=RELEVANT), retrieved_files=["a.py", "x.py"]
    )

    assert set(score_case(outcome, 5)) == {
        "recall@5",
        "precision@5",
        "hit@5",
        "mrr",
        "ndcg@5",
    }


def test_summary_averages_cases_and_reports_latency() -> None:
    outcomes = [
        CaseOutcome(
            case=EvaluationCase(query="q1", relevant_files=frozenset({"a.py"})),
            retrieved_files=["a.py"],
            latency_ms=10.0,
        ),
        CaseOutcome(
            case=EvaluationCase(query="q2", relevant_files=frozenset({"b.py"})),
            retrieved_files=["x.py"],
            latency_ms=30.0,
        ),
    ]

    summary = summarise(outcomes, k=3)

    assert summary["recall@3"] == 0.5
    assert summary["mrr"] == 0.5
    assert summary["cases"] == 2.0
    assert summary["latency_p50_ms"] in (10.0, 30.0)
    assert summary["latency_p95_ms"] == 30.0
    # Per-case metrics are kept, so a benchmark can show which queries failed.
    assert outcomes[1].metrics["hit@3"] == 0.0


def test_empty_summary() -> None:
    assert summarise([], k=5) == {}


def test_evaluation_cases_can_be_loaded_from_json() -> None:
    case = EvaluationCase.from_dict(
        {"query": "hash a password", "relevant_files": ["app/auth/passwords.py"], "note": "phase 4"}
    )

    assert case.relevant_files == frozenset({"app/auth/passwords.py"})
    assert case.note == "phase 4"


def test_chunk_results_collapse_to_a_ranked_file_list() -> None:
    assert unique_files(["a.py", "a.py", "b.py", "a.py"]) == ["a.py", "b.py"]

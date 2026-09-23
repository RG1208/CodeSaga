"""Retrieval metrics.

Evaluation is at the **file** level: a query names the files a good answer must come
from, and a strategy is judged on whether it retrieved chunks from those files. That
keeps ground truth cheap to write and stable while chunking changes.

    recall@k     share of the relevant files that appear in the top k
    precision@k  share of the top k results that are relevant
    hit@k        1 if any relevant file appears in the top k, else 0
    MRR          1 / rank of the first relevant result (0 if none)
    nDCG@k       rank-weighted gain, so being right at rank 1 beats rank 10
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    """A query and the files a correct answer should come from."""

    query: str
    relevant_files: frozenset[str]
    note: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationCase":
        return cls(
            query=payload["query"],
            relevant_files=frozenset(payload["relevant_files"]),
            note=payload.get("note"),
        )


@dataclass
class CaseOutcome:
    """What one strategy retrieved for one case (file paths, best rank first)."""

    case: EvaluationCase
    retrieved_files: list[str]
    latency_ms: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)


def recall_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    found = {path for path in retrieved[:k] if path in relevant}
    return len(found) / len(relevant)


def precision_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for path in top if path in relevant) / len(top)


def hit_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    return 1.0 if any(path in relevant for path in retrieved[:k]) else 0.0


def reciprocal_rank(retrieved: Sequence[str], relevant: frozenset[str]) -> float:
    for position, path in enumerate(retrieved, start=1):
        if path in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    gain = sum(
        1.0 / math.log2(position + 1)
        for position, path in enumerate(retrieved[:k], start=1)
        if path in relevant
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return gain / ideal if ideal else 0.0


def score_case(outcome: CaseOutcome, k: int) -> dict[str, float]:
    retrieved, relevant = outcome.retrieved_files, outcome.case.relevant_files
    return {
        f"recall@{k}": recall_at_k(retrieved, relevant, k),
        f"precision@{k}": precision_at_k(retrieved, relevant, k),
        f"hit@{k}": hit_at_k(retrieved, relevant, k),
        "mrr": reciprocal_rank(retrieved, relevant),
        f"ndcg@{k}": ndcg_at_k(retrieved, relevant, k),
    }


def summarise(outcomes: Sequence[CaseOutcome], k: int) -> dict[str, float]:
    """Metrics averaged over cases, plus latency percentiles."""
    if not outcomes:
        return {}
    for outcome in outcomes:
        outcome.metrics = score_case(outcome, k)
    names = list(outcomes[0].metrics)
    summary = {
        name: round(mean(outcome.metrics[name] for outcome in outcomes), 4) for name in names
    }
    latencies = sorted(outcome.latency_ms for outcome in outcomes)
    summary["latency_p50_ms"] = round(_percentile(latencies, 0.50), 2)
    summary["latency_p95_ms"] = round(_percentile(latencies, 0.95), 2)
    summary["cases"] = float(len(outcomes))
    return summary


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[position]


def unique_files(paths: Sequence[str]) -> list[str]:
    """Collapse per-chunk results into the ranked list of distinct files."""
    seen: list[str] = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return seen

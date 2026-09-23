"""Combining two ranked lists into one.

Two standard methods, both configurable because which one wins is an empirical
question this project intends to measure:

* **Reciprocal rank fusion (RRF)** uses only positions: `Σ weight / (k + rank)`. Scores
  from different retrievers are not comparable (BM25 is unbounded, cosine is 0-1), and
  RRF sidesteps that entirely. It is the default.
* **Weighted score fusion** min-max normalises each list to 0-1 and adds them with
  weights. It keeps score *margins*, which RRF throws away.
"""

from dataclasses import dataclass, field
from typing import Literal

FusionMethod = Literal["rrf", "weighted"]


@dataclass
class ScoredChunk:
    chunk_id: str
    score: float
    rank: int = 0
    # Per-retriever detail kept for the response and for research logs:
    # {"bm25": 12.3, "bm25_rank": 1, "dense": 0.71, "dense_rank": 4, "rerank": 5.2}
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FusionConfig:
    method: FusionMethod = "rrf"
    bm25_weight: float = 0.5
    dense_weight: float = 0.5
    rrf_k: int = 60

    def to_dict(self) -> dict[str, float | str | int]:
        return {
            "method": self.method,
            "bm25_weight": self.bm25_weight,
            "dense_weight": self.dense_weight,
            "rrf_k": self.rrf_k,
        }


def _normalise(results: list[ScoredChunk]) -> dict[str, float]:
    """Min-max to 0-1; a single result (or a tie) maps to 1.0."""
    if not results:
        return {}
    scores = [item.score for item in results]
    lowest, highest = min(scores), max(scores)
    if highest - lowest < 1e-12:
        return {item.chunk_id: 1.0 for item in results}
    return {item.chunk_id: (item.score - lowest) / (highest - lowest) for item in results}


def fuse(
    ranked_lists: dict[str, list[ScoredChunk]],
    config: FusionConfig,
    weights: dict[str, float] | None = None,
) -> list[ScoredChunk]:
    """Merge named ranked lists (e.g. {"bm25": [...], "dense": [...]}) into one ranking."""
    weights = weights or {"bm25": config.bm25_weight, "dense": config.dense_weight}
    components: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}

    for source, results in ranked_lists.items():
        weight = weights.get(source, 1.0)
        normalised = _normalise(results) if config.method == "weighted" else {}
        for position, item in enumerate(results, start=1):
            detail = components.setdefault(item.chunk_id, {})
            detail[source] = item.score
            detail[f"{source}_rank"] = float(position)
            contribution = (
                weight / (config.rrf_k + position)
                if config.method == "rrf"
                else weight * normalised.get(item.chunk_id, 0.0)
            )
            totals[item.chunk_id] = totals.get(item.chunk_id, 0.0) + contribution

    # Ties break on chunk id so results are reproducible run to run.
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [
        ScoredChunk(chunk_id=chunk_id, score=score, rank=rank, components=components[chunk_id])
        for rank, (chunk_id, score) in enumerate(ordered, start=1)
    ]

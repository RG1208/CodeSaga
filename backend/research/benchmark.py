"""Compare retrieval strategies on a query set.

This is the research harness for Phase 4: it runs the same queries through every
strategy and prints recall/precision/MRR/nDCG plus latency percentiles, so changes to
chunking, weights or models can be judged on numbers rather than impressions.

Two targets:

    # the deterministic fixture repository — offline, no database, no server
    python -m research.benchmark --fixture support_desk

    # a repository that has been indexed through the API
    python -m research.benchmark --repository <uuid-or-name>

Ground truth is a JSON list of {"query": ..., "relevant_files": [...]} objects (see
research/query_sets/). Evaluation is at file level, so the query set survives changes
to chunking. Add --json results.json to keep the raw per-query output.
"""

import argparse
import json
import sys
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models.repository import Repository
from app.models.retrieval import CodeChunk
from app.retrieval.embeddings import create_embedding_provider
from app.retrieval.engine import RetrievalEngine, RetrievalStrategy, SearchOptions
from app.retrieval.errors import RetrievalError
from app.retrieval.index_store import RepositoryIndexStore
from app.retrieval.rerankers import create_reranker_registry
from research.metrics import CaseOutcome, EvaluationCase, summarise, unique_files

DEFAULT_QUERY_SETS = Path(__file__).resolve().parent / "query_sets"
METRIC_ORDER = ("recall", "precision", "hit", "mrr", "ndcg")


class Target:
    """Something searchable: an engine plus the file path of every chunk id."""

    def __init__(
        self,
        name: str,
        engine: RetrievalEngine,
        files: dict[str, str],
        settings: Settings,
        chunk_count: int,
    ) -> None:
        self.name = name
        self.engine = engine
        self.files = files
        self.settings = settings
        self.chunk_count = chunk_count


def fixture_target(project: str, settings: Settings) -> Target:
    """The test fixture, chunked and indexed in a temporary directory."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.retrieval.helpers import build_fixture_index

    root = Path(tempfile.mkdtemp(prefix="codesage-benchmark-"))
    fixture = build_fixture_index(
        root,
        project=project,
        embeddings=create_embedding_provider(settings),
        settings=settings.model_copy(update={"index_storage_dir": root / "indexes"}),
    )
    files = {str(chunk.chunk_id): chunk.file_path for chunk in fixture.chunks}
    print(f"fixture {project}: {len(fixture.chunks)} chunks, index at {root}")
    return Target(project, fixture.engine(), files, fixture.settings, len(fixture.chunks))


def repository_target(reference: str, settings: Settings) -> Target:
    """A repository indexed through the API, read from the database and the index store."""
    from app.db.session import get_session_factory

    with get_session_factory()() as session:
        query = select(Repository)
        try:
            repository = session.get(Repository, uuid.UUID(reference))
        except ValueError:
            repository = session.scalars(query.where(Repository.name == reference)).first()
        if repository is None:
            raise SystemExit(f"No repository matches {reference!r}.")
        rows = session.execute(
            select(CodeChunk.id, CodeChunk.file_path, CodeChunk.content).where(
                CodeChunk.repository_id == repository.id
            )
        ).all()
        if not rows:
            raise SystemExit(f"{repository.name} has no chunks; index it first.")
        files = {str(row.id): row.file_path for row in rows}
        documents = {str(row.id): row.content for row in rows}

    embeddings = create_embedding_provider(settings)
    store = RepositoryIndexStore(settings.index_storage_dir)
    index = store.load(
        repository.id,
        commit_sha=repository.commit_sha,
        embeddings=embeddings,
        settings=settings,
    )
    engine = RetrievalEngine(
        index,
        embeddings,
        lambda chunk_ids: {cid: documents[cid] for cid in chunk_ids if cid in documents},
        settings,
    )
    print(f"{repository.name}: {len(rows)} chunks, commit {repository.commit_sha}")
    return Target(repository.name, engine, files, settings, len(rows))


def load_cases(path: Path) -> list[EvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["queries"] if isinstance(payload, dict) else payload
    return [EvaluationCase.from_dict(case) for case in cases]


def run_strategy(
    target: Target,
    strategy: RetrievalStrategy,
    cases: Sequence[EvaluationCase],
    *,
    top_k: int,
    reranker_name: str | None,
    repeats: int,
) -> tuple[dict[str, float], list[CaseOutcome]]:
    reranker = None
    if strategy is RetrievalStrategy.HYBRID_RERANK:
        registry = create_reranker_registry(target.settings)
        name = reranker_name or registry.default
        if name is None:
            raise SystemExit("hybrid_rerank needs a reranker (set RERANKER_PROVIDER).")
        reranker = registry.get(name)

    options = SearchOptions.from_settings(target.settings)
    outcomes: list[CaseOutcome] = []
    for case in cases:
        latencies: list[float] = []
        outcome = None
        for _ in range(repeats):
            outcome = target.engine.search(
                case.query, strategy=strategy, top_k=top_k, options=options, reranker=reranker
            )
            latencies.append(outcome.timings["total_ms"])
        assert outcome is not None
        outcomes.append(
            CaseOutcome(
                case=case,
                retrieved_files=unique_files(
                    [target.files.get(item.chunk_id, "?") for item in outcome.items]
                ),
                latency_ms=min(latencies),
            )
        )
    return summarise(outcomes, k=top_k), outcomes


def print_table(results: dict[str, dict[str, float]]) -> None:
    names = list(results)
    metrics = [
        key
        for key in next(iter(results.values()))
        if key.startswith(METRIC_ORDER) or key.startswith("latency")
    ]
    width = max(len(name) for name in [*names, "strategy"]) + 2
    header = f"{'strategy':<{width}}" + "".join(f"{metric:>16}" for metric in metrics)
    print("\n" + header)
    print("-" * len(header))
    for name, summary in results.items():
        row = f"{name:<{width}}" + "".join(f"{summary.get(metric, 0):>16.3f}" for metric in metrics)
        print(row)


def print_misses(name: str, outcomes: Sequence[CaseOutcome], top_k: int) -> None:
    misses = [outcome for outcome in outcomes if outcome.metrics.get(f"hit@{top_k}", 0) == 0]
    if not misses:
        return
    print(f"\n{name}: {len(misses)} query(ies) found nothing relevant")
    for outcome in misses:
        expected = ", ".join(sorted(outcome.case.relevant_files))
        got = ", ".join(outcome.retrieved_files[:3]) or "nothing"
        print(f"  {outcome.case.query!r}\n    expected: {expected}\n    got:      {got}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", help="Benchmark a test fixture project, e.g. support_desk.")
    source.add_argument("--repository", help="Benchmark an indexed repository (uuid or name).")
    parser.add_argument("--queries", type=Path, help="Query set JSON (default: the fixture's own).")
    parser.add_argument(
        "--strategies",
        default="bm25,dense,hybrid,hybrid_rerank",
        help="Comma-separated strategies to compare.",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--reranker", help="Reranker name for hybrid_rerank.")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Runs per query; the fastest is reported (warm-cache latency).",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["fastembed", "hashing"],
        help="Override the configured provider (hashing is offline and deterministic).",
    )
    parser.add_argument("--json", type=Path, help="Write the full results here.")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.embedding_provider:
        settings = settings.model_copy(update={"embedding_provider": args.embedding_provider})

    if args.fixture:
        target = fixture_target(args.fixture, settings)
        queries = args.queries or DEFAULT_QUERY_SETS / f"{args.fixture}.json"
    else:
        target = repository_target(args.repository, settings)
        queries = args.queries
        if queries is None:
            raise SystemExit("--repository needs --queries.")
    cases = load_cases(Path(queries))
    print(f"{len(cases)} queries, top_k={args.top_k}, embeddings={settings.embedding_provider}")

    results: dict[str, dict[str, float]] = {}
    detail: dict[str, Any] = {}
    for name in [item.strip() for item in args.strategies.split(",") if item.strip()]:
        strategy = RetrievalStrategy(name)
        try:
            summary, outcomes = run_strategy(
                target,
                strategy,
                cases,
                top_k=args.top_k,
                reranker_name=args.reranker,
                repeats=args.repeats,
            )
        except RetrievalError as exc:
            print(f"{name}: unavailable ({exc.message})")
            continue
        results[name] = summary
        detail[name] = [
            {
                "query": outcome.case.query,
                "relevant_files": sorted(outcome.case.relevant_files),
                "retrieved_files": outcome.retrieved_files,
                "latency_ms": outcome.latency_ms,
                **outcome.metrics,
            }
            for outcome in outcomes
        ]
        print_misses(name, outcomes, args.top_k)

    if not results:
        return 1
    print_table(results)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "target": target.name,
                    "chunks": target.chunk_count,
                    "top_k": args.top_k,
                    "embedding_provider": settings.embedding_provider,
                    "embedding_model": settings.embedding_model,
                    "summary": results,
                    "queries": detail,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Tests

Tests live next to the code they exercise, plus cross-service checks here.

| Location | What it covers | How to run (from `backend/`, venv active) |
| --- | --- | --- |
| `backend/tests/unit/test_sources.py` | GitHub URL, branch-name and local-path validation, including attack strings (`ext::`, `--upload-pack`, `..`, symlink escapes) | `pytest tests/unit/test_sources.py` |
| `backend/tests/unit/test_storage.py` | Storage paths derived from UUIDs, traversal/symlink escapes refused, atomic checkout replacement | `pytest tests/unit/test_storage.py` |
| `backend/tests/unit/test_scanner.py` | Metadata extraction: ignored folders, symlinks, languages, manifests, README/LICENSE, binary detection, hashes | `pytest tests/unit/test_scanner.py` |
| `backend/tests/unit/test_git_client.py` | Real git against local repositories: resolve, clone, branches, symlinks as text, hooks/fsmonitor never run, env scrubbing, timeout/cancel | `pytest tests/unit/test_git_client.py` |
| `backend/tests/unit/test_indexer.py` | The pipeline: success, failures, previous index kept on failure, limits, cancellation, restart recovery, real local repo end to end | `pytest tests/unit/test_indexer.py` |
| `backend/tests/unit/test_jobs.py` | Inline and thread job queues, error containment, shutdown signalling | `pytest tests/unit/test_jobs.py` |
| `backend/tests/unit/` (other) | Settings parsing, log formatting | `pytest tests/unit` |
| `backend/tests/analysis/test_python_analyzer.py` | Python symbols, parameters, decorators, docstrings, imports, exports, exact line ranges, syntax-error tolerance | `pytest tests/analysis/test_python_analyzer.py` |
| `backend/tests/analysis/test_ecmascript_analyzer.py` | JS/TS/TSX imports, exports, classes, types, React components/hooks/renders, API calls, decorators, line ranges | `pytest tests/analysis/test_ecmascript_analyzer.py` |
| `backend/tests/analysis/test_resolver.py` | Import resolution: Python packages/relative/ambiguous, tsconfig aliases, extensions, index files, escapes | `pytest tests/analysis/test_resolver.py` |
| `backend/tests/analysis/test_graph.py` | Whole fixture projects: confirmed import edges, inferred calls/renders/inherits with resolution strategies, summary | `pytest tests/analysis/test_graph.py` |
| `backend/tests/analysis/test_parser_stability.py` | Parses many real files repeatedly in a subprocess; guards against native parser crashes | `pytest tests/analysis/test_parser_stability.py` |
| `backend/tests/api/test_code.py` | Code endpoints: files, content (path-traversal attempts), detail, symbols, search, dependencies | `pytest tests/api/test_code.py` |
| `backend/tests/retrieval/test_tokenizer.py` | Code-aware tokenisation: identifier splitting, digits, paths, stemming, stopwords | `pytest tests/retrieval/test_tokenizer.py` |
| `backend/tests/retrieval/test_chunking.py` | Chunking: whole symbols, split classes, oversized functions, module gaps, Markdown sections, metadata, deterministic ids | `pytest tests/retrieval/test_chunking.py` |
| `backend/tests/retrieval/test_bm25.py` | BM25 scoring, `k1`/`b` behaviour, ranking, save/load round trip | `pytest tests/retrieval/test_bm25.py` |
| `backend/tests/retrieval/test_embeddings.py`, `test_vector_store.py`, `test_fusion.py` | Provider contract and determinism, FAISS cosine search and persistence, RRF and weighted fusion | `pytest tests/retrieval` |
| `backend/tests/retrieval/test_index_store.py` | Index directories: manifest, stale commit, model mismatch, unreadable index, install/remove, caching | `pytest tests/retrieval/test_index_store.py` |
| `backend/tests/retrieval/test_engine.py` | **All four strategies** over the fixture repository: recall/MRR, scores, fusion weights, reranking, metadata preservation | `pytest tests/retrieval/test_engine.py` |
| `backend/tests/retrieval/test_metrics.py` | Research metrics: recall@k, precision@k, hit@k, MRR, nDCG@k, summaries | `pytest tests/retrieval/test_metrics.py` |
| `backend/tests/retrieval/test_real_models.py` | **Opt-in:** real BGE embeddings and cross-encoder on paraphrased queries | `REAL_MODEL_TESTS=1 pytest tests/retrieval/test_real_models.py` |
| `backend/tests/api/test_search.py` | The search endpoint: every strategy, metadata, options, validation, research logging, 404/409/422/503 | `pytest tests/api/test_search.py` |
| `backend/tests/api/` | HTTP endpoints end to end through FastAPI: health, errors, CORS, projects, and all repository endpoints (add, list, detail, index, delete) | `pytest tests/api` |
| `backend/tests/test_migrations.py` | Alembic migrations apply, match the ORM models, and roll back | `pytest tests/test_migrations.py` |
| `tests/smoke/` | The **running** app: backend, database, CORS, the search route and frontend pages together | `python3 tests/smoke/smoke_test.py` (from the repo root) |

## Backend tests

They use in-memory SQLite by default and never touch the network: GitHub is
replaced by `FakeGitClient` (`tests/fakes.py`), embeddings by the deterministic
`HashingEmbeddingProvider`, reranking by `KeywordReranker`, and jobs run inline so
an indexing request finishes before the response. Git-client tests create real
repositories in a temporary directory (they are skipped if git is not installed).
No test downloads a model unless `REAL_MODEL_TESTS=1` is set.

```bash
cd backend
source .venv/bin/activate
pytest
```

To run the same suite against PostgreSQL, create a **separate, disposable**
database (tests drop all tables after each test) and point `TEST_DATABASE_URL` at it:

```bash
sudo -u postgres psql -c "CREATE DATABASE codesage_test OWNER codesage;"
TEST_DATABASE_URL=postgresql+psycopg://codesage:codesage@localhost:5432/codesage_test pytest
```

## Code-analysis fixtures

Analysis tests use two small sample projects in `backend/tests/fixtures/code/`
(`python_project` and `ts_project`). They are only parsed, never run, and excluded from
Ruff. Expected line numbers are derived from the fixture text (`line_of(...)`), so the
fixtures can be edited without renumbering tests.

## Retrieval fixture and benchmark

Retrieval tests index `backend/tests/fixtures/retrieval/support_desk/` — 15 files
(502 lines) with one concept per file: password hashing, tokens, payments,
refunds, email, SMS, rate limiting, caching, database pooling, tickets,
escalation, a TypeScript API client, a TSX login form and Markdown docs. One
concept per file makes "did retrieval find the right file" unambiguous, which is
what the strategy tests assert.

The same fixture and ground-truth query set drive the benchmark:

```bash
cd backend
.venv/bin/python -m research.benchmark --fixture support_desk --top-k 5
.venv/bin/python -m research.benchmark --fixture support_desk --embedding-provider hashing  # offline
```

Numbers and interpretation: [docs/retrieval.md](../docs/retrieval.md).

## Smoke test

Start the backend and frontend in their two terminals first (see the README),
then from the repo root:

```bash
python3 tests/smoke/smoke_test.py
```

It uses only the Python standard library. Override the targets with `API_URL`
and `FRONTEND_URL` if you run on other ports.

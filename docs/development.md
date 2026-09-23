# Development Guide

Everything runs directly on your machine: PostgreSQL as a normal system service,
and the backend and frontend in two terminals. First-time setup (creating the
database, virtualenv and npm packages) is in the [README](../README.md#one-time-setup).

## Daily workflow

1. **Make sure PostgreSQL is running**

   ```bash
   pg_isready -h localhost -p 5432        # "accepting connections" means it is up
   sudo systemctl start postgresql        # Linux, if it is not
   brew services start postgresql@16      # macOS (use your installed version)
   ```

2. **Terminal 1 — backend**

   ```bash
   cd backend
   source .venv/bin/activate              # Windows: .venv\Scripts\activate
   alembic upgrade head                   # only needed after pulling new migrations
   uvicorn app.main:app --reload
   ```

   - API: http://localhost:8000
   - Swagger UI: http://localhost:8000/docs
   - Health: http://localhost:8000/api/v1/health/ready

   `--reload` restarts the server whenever a Python file changes. To use another
   port: `uvicorn app.main:app --reload --port 8001` (then point the frontend at
   it, see [Configuration](#configuration)).

3. **Terminal 2 — frontend**

   ```bash
   cd frontend
   npm run dev
   ```

   Open http://localhost:3000. Edits appear instantly (Fast Refresh).

4. **Stop** with `Ctrl+C` in each terminal.

The header of the web app shows an **API status pill**: green means the backend
and database are reachable, amber means the backend is up but the database is
not, red means the backend is not running.

## Working with repositories

- **Add** from the UI (**Repositories → Add repository**) or the API. Adding checks
  the repository with `git ls-remote`, so it needs network access.
- **Index** with the button on the details page, or leave "Start indexing right
  away" ticked when adding. Status and progress update every 2 seconds.
- **Checkouts** live in `data/repositories/<repository-id>/` (setting
  `REPOSITORY_STORAGE_DIR`). They are shallow clones — safe to delete by deleting
  the repository in CodeSage; don't edit files there.
- **Local repositories** (development only) must be inside `LOCAL_REPOSITORY_ROOTS`
  (default: your home directory). Only committed files on the selected branch are
  indexed — uncommitted changes are not.
- **Browse code** with **Browse code** on a repository page (`/repositories/<id>/code`):
  file tree, source, symbols, imports and dependency diagrams. Repositories indexed
  before code analysis existed need a **Re-index** first.
- **Search code** with `POST /api/v1/repositories/<id>/search` (there is no search UI
  yet — the chat interface is a later phase). The **Search index** card on the
  repository page shows the chunk count, BM25 terms and embedding model. Index files
  live in `data/indexes/<repository-id>/` (setting `INDEX_STORAGE_DIR`); the
  embedding model is downloaded once into `data/models/` (`EMBEDDING_CACHE_DIR`).
- **Restarting the backend** (including a `--reload` after you save a Python file)
  interrupts running indexing jobs. They are marked failed with "Indexing was
  interrupted…"; click **Re-index**.

Clean slate for repositories (database rows and checkouts):

```bash
cd backend && source .venv/bin/activate
psql "postgresql://codesage:codesage@localhost:5432/codesage" \
  -c "DELETE FROM repositories;"        # cascades to jobs, files, analysis and chunks
rm -rf ../data/repositories ../data/indexes
```

(`retrieval_logs` survives on purpose — it is research data. Delete it explicitly
if you want a truly clean slate.)

How the pipeline, job queue and security protections work is explained in
[ingestion.md](ingestion.md); chunking, the strategies and the search API in
[retrieval.md](retrieval.md).

### Trying the search strategies

```bash
API=localhost:8000/api/v1
for strategy in bm25 dense hybrid hybrid_rerank; do
  echo "== $strategy"
  curl -s -X POST $API/repositories/$REPO_ID/search -H 'Content-Type: application/json' \
    -d "{\"query\": \"how are passwords hashed\", \"top_k\": 3, \"retrieval_strategy\": \"$strategy\"}" \
    | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["latency_ms"], "ms"); [print(" ", i["rank"], i["chunk"]["file_path"], i["chunk"]["start_line"], round(i["score"],4)) for i in r["results"]]'
done
```

Or measure them over a query set with metrics instead of eyeballing:

```bash
cd backend
.venv/bin/python -m research.benchmark --fixture support_desk --top-k 5
.venv/bin/python -m research.benchmark --repository <name-or-id> --queries my_queries.json
```

## Configuration

| What | Where | Picked up |
| --- | --- | --- |
| Backend settings (database URL, CORS, logging, ingestion limits, job workers…) | repo-root `.env` (template: `.env.example`) | when the backend starts — restart Terminal 1 |
| Frontend API URL (`NEXT_PUBLIC_API_BASE_URL`) | `frontend/.env.local` (optional) | when `npm run dev` starts — restart Terminal 2 |

Real environment variables override `.env`, e.g.
`LOG_LEVEL=DEBUG uvicorn app.main:app --reload`.

## Database

```bash
psql "postgresql://codesage:codesage@localhost:5432/codesage"   # SQL shell
\dt                                                              # list tables (inside psql)
```

Load demo data (safe to run repeatedly; it skips what already exists):

```bash
cd backend && source .venv/bin/activate
python -m app.db.seed
```

Reset the database to empty tables:

```bash
alembic downgrade base && alembic upgrade head
```

### Migrations

Change a model in `backend/app/models/`, then (in `backend/`, venv active):

```bash
alembic revision --autogenerate -m "add xyz"   # generate a migration file
# review the new file in alembic/versions/ — autogenerate is not perfect
alembic upgrade head                           # apply it
alembic check                                  # confirm models and schema match
alembic downgrade -1                           # roll back one step if needed
alembic current                                # show the applied revision
```

A new model must also be imported in `app/models/__init__.py`, or Alembic will
not see it.

## Tests and quality checks

```bash
cd backend && source .venv/bin/activate
pytest                     # all backend tests (in-memory SQLite, no server or network needed)
pytest tests/api -k health # a subset
pytest tests/unit/test_sources.py tests/unit/test_git_client.py   # security-focused tests
pytest tests/analysis      # parsers, import resolution, dependency graph
pytest tests/retrieval tests/api/test_search.py   # chunking, BM25, dense, hybrid, reranking, search API
REAL_MODEL_TESTS=1 pytest tests/retrieval/test_real_models.py   # opt-in: downloads the real models
ruff check . && ruff format --check .

cd frontend
npm run lint
npm run typecheck
npm run build              # production build

scripts/check.sh           # all of the above, from the repo root
python3 tests/smoke/smoke_test.py   # end-to-end, while both servers run
```

## Adding an API endpoint

1. **Schema** — request/response models in `backend/app/schemas/`.
2. **Repository** — any new queries in `backend/app/repositories/`.
3. **Service** — business rules in `backend/app/services/`; raise `NotFoundError` /
   `ConflictError` instead of returning error values.
4. **Endpoint** — thin handler in `backend/app/api/v1/endpoints/`, registered in
   `backend/app/api/v1/router.py`.
5. **Tests** — add API tests in `backend/tests/api/`.
6. **Frontend** — add the type to `frontend/src/lib/api/types.ts` and a function to
   `frontend/src/lib/api/endpoints.ts`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `uvicorn: command not found` / `alembic: command not found` | The virtualenv is not active: `source .venv/bin/activate` inside `backend/`. |
| `ModuleNotFoundError: No module named 'app'` | Run backend commands from inside `backend/`. |
| `connection refused` … port 5432 | PostgreSQL is not running — see step 1 of the daily workflow. |
| `password authentication failed for user "codesage"` | The database user does not exist or has another password — redo README setup step 1, or fix `DATABASE_URL` in `.env`. |
| `database "codesage" does not exist` | Run the `CREATE DATABASE` command from README setup step 1. |
| `relation "projects" does not exist` | Tables are missing: `alembic upgrade head`. |
| `[Errno 98] address already in use` (port 8000) | Another backend is running. Stop it, or use `--port 8001` and set `NEXT_PUBLIC_API_BASE_URL`. |
| Next.js says port 3000 is in use and picks 3001 | Stop the other process, or add `http://localhost:3001` to `CORS_ORIGINS` in `.env` and restart the backend. |
| Frontend shows "Cannot reach the CodeSage API" | Terminal 1 is not running, or `NEXT_PUBLIC_API_BASE_URL` points elsewhere. |
| Browser console shows a CORS error | The frontend's origin is missing from `CORS_ORIGINS` in `.env`; add it and restart the backend. |
| API status pill is amber | Backend is up but PostgreSQL is unreachable — check it is running and `DATABASE_URL` is right. |
| `column repositories.owner does not exist` (or similar) | Migration `0002` is not applied: `alembic upgrade head`, then restart the backend. |
| Adding a repository says "Repository not found or not public" | The URL is wrong, the repository is private, or it was renamed. Only public GitHub repositories are supported. |
| Adding a repository returns "Could not reach the repository host" (502) | No network access to github.com from the backend machine, or a proxy is required (`HTTPS_PROXY`). |
| "git is not installed on the server" | Install git and make sure it is on `PATH` for the terminal running uvicorn. |
| Indexing failed: "Indexing was interrupted because the server stopped" | The backend restarted mid-job (often `--reload` after a code edit). Click **Re-index**. |
| Indexing failed: "larger than the … MB limit" / "more than … files" | Raise `MAX_REPOSITORY_SIZE_MB` / `MAX_REPOSITORY_FILES` in `.env` and restart the backend. |
| Local path rejected: "must be inside an allowed directory" | Add its parent directory to `LOCAL_REPOSITORY_ROOTS` in `.env` and restart the backend. |
| Local path rejected with 403 | `APP_ENV` is not `development`; local repositories are disabled elsewhere. |
| Status stuck on "Queued" | All `JOB_WORKERS` are busy with other repositories; it starts when one finishes. |
| `ModuleNotFoundError: No module named 'tree_sitter'` | Dependencies are outdated: `pip install -r requirements-dev.txt` in `backend/`. |
| Code explorer says the repository "was indexed before code analysis was available" | Click **Re-index** on the repository page. |
| A file is marked "Parsed partially" | It has a syntax error, or syntax the Tree-sitter grammar does not support yet. Everything else in the file is still extracted. |
| A file shows no symbols / "not parsed" | Only Python, JavaScript, TypeScript and TSX are analyzed; files over `MAX_PARSED_FILE_SIZE_KB` and `*.min.js` are skipped. |
| A call you expected is missing from "Uses / Used by" | Calls are matched by name only; calls through parameters, object attributes or dynamic code are not linked (see [code-analysis.md](code-analysis.md#known-limitations)). |
| First indexing run pauses for a while at "Building search index" | The embedding model (~100 MB) is being downloaded into `data/models/`. Later runs read it from disk. |
| Repository page says "Dense index unavailable" | The embedding model could not be loaded (usually no network on the first run). BM25 search still works; **Re-index** once the model can be downloaded, or set `EMBEDDING_PROVIDER=hashing` / `DENSE_RETRIEVAL_ENABLED=false`. |
| Search returns 409 `index_out_of_date` | The repository was re-cloned but the index was not rebuilt. Click **Re-index**. |
| Search returns 409 `repository_not_indexed` / `index_not_built` | The repository has never finished indexing, or `RETRIEVAL_ENABLED` was false when it did. Index it again. |
| Search returns 503 with `hybrid_rerank` | The reranker model is unavailable; use `hybrid`, or set `RERANKER_PROVIDER=none` to make the failure explicit. |
| `hybrid_rerank` takes about a second | Expected on CPU: the cross-encoder scores `RERANK_CANDIDATES` chunks. Lower it, or use `hybrid`. |
| `ModuleNotFoundError: No module named 'fastembed'` / `'faiss'` | Dependencies are outdated: `pip install -r requirements-dev.txt` in `backend/`. |
| Changed `.env` / `.env.local` has no effect | Restart the corresponding terminal's server. |

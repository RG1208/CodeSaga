# CodeSage

**AI-powered codebase intelligence and review platform.** CodeSage will ingest
repositories, understand their structure, answer questions with exact source
references, and assist with code review.

> **Status: Phase 4 — Code retrieval.** Add public GitHub repositories (or local
> git repositories in development); CodeSage clones and indexes them in the
> background, parses Python, JavaScript, TypeScript and TSX with Tree-sitter into
> symbols, imports and a dependency graph you can browse, and builds a searchable
> index — code-aware chunks, BM25, BGE embeddings, hybrid fusion and optional
> reranking — behind `POST /api/v1/repositories/{id}/search`. Repository code is
> never executed. LLM answers and the chat interface arrive in later phases.

## What you can do

1. **Add a repository** — paste `https://github.com/owner/repo` (optionally pick a
   branch), or a local repository path in development mode.
2. **Index it** — CodeSage makes a shallow clone, detects languages, manifests,
   README and license, and builds a file index (line counts and content hashes).
3. **Watch progress** — queued → cloning → analyzing → indexing → parsing → embedding → completed.
4. **Explore metadata** — commit SHA, languages, file counts, last commit.
5. **Browse the code** — file explorer, source viewer, functions/classes/methods with
   parameters, decorators and docstrings, imports and exports, React components and
   hooks, API calls, and a dependency view that separates **confirmed** file imports
   from **inferred** calls.
6. **Search it** — `POST /api/v1/repositories/{id}/search` retrieves the most
   relevant chunks with their file paths, line ranges and scores, using `bm25`,
   `dense`, `hybrid` or `hybrid_rerank`. Compare the strategies with
   `python -m research.benchmark`. No UI for search yet — the chat interface is a
   later phase.
7. **Re-index or delete** — re-indexing picks up new commits; deleting removes the
   index, the analysis, the search index and the local checkout.

## Tech stack

| Area | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript 5, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic 2, SQLAlchemy 2, Alembic, Git CLI |
| Code analysis | Tree-sitter (Python, JavaScript, TypeScript, TSX grammars) |
| Retrieval | BM25 (NumPy), BGE embeddings via fastembed/ONNX Runtime, FAISS, cross-encoder reranking |
| Database | PostgreSQL (SQLite in-memory for tests) |
| Quality | pytest, Ruff, ESLint, TypeScript compiler |

Full list with versions and what each piece does: **[docs/tech-stack.md](docs/tech-stack.md)**.

## Prerequisites

| Tool | Version | Check with |
| --- | --- | --- |
| Python | 3.12 or newer | `python3 --version` |
| Node.js (includes npm) | 20.9 or newer | `node --version` |
| PostgreSQL | 14 or newer, running on port 5432 | `psql --version` |
| Git | 2.30 or newer (used to clone repositories) | `git --version` |

## One-time setup

Do these steps once, from the repository root.

### 1. Create the database

Create a `codesage` user (password `codesage`) and a `codesage` database:

```bash
# Linux (Ubuntu/Debian)
sudo -u postgres psql -c "CREATE ROLE codesage WITH LOGIN PASSWORD 'codesage';"
sudo -u postgres psql -c "CREATE DATABASE codesage OWNER codesage;"
```

<details>
<summary>macOS (Homebrew) or Windows</summary>

- **macOS:** `psql postgres -c "CREATE ROLE codesage WITH LOGIN PASSWORD 'codesage';"`
  then `psql postgres -c "CREATE DATABASE codesage OWNER codesage;"`
- **Windows:** open *SQL Shell (psql)*, log in as `postgres`, and run:
  `CREATE ROLE codesage WITH LOGIN PASSWORD 'codesage';` then
  `CREATE DATABASE codesage OWNER codesage;`
</details>

Check it works:

```bash
psql "postgresql://codesage:codesage@localhost:5432/codesage" -c "SELECT 1;"
```

If you use a different user, password or port, change `DATABASE_URL` in `.env` (next step).

### 2. Backend

```bash
cp .env.example .env

cd backend
python3 -m venv .venv                  # create a virtual environment
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt    # install Python packages
alembic upgrade head                   # create the database tables
python -m app.db.seed                  # optional: register two small demo repositories
cd ..
```

### 3. Frontend

```bash
cd frontend
npm install
cd ..
```

> Shortcut: after step 1, `scripts/setup.sh` performs steps 2 and 3 (except seeding).

## Run the app — two terminals

**Terminal 1 — backend**

```bash
cd backend
source .venv/bin/activate              # Windows: .venv\Scripts\activate
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000 — interactive docs at http://localhost:8000/docs.

**Terminal 2 — frontend**

```bash
cd frontend
npm run dev
```

Open **http://localhost:3000**.

Both servers reload automatically when you edit code. Stop each with `Ctrl+C`.
Make sure PostgreSQL is running before starting the backend. When you pull
changes that add a migration, run `alembic upgrade head` in Terminal 1 before
starting the backend.

> **Upgrading from an earlier phase?** Stop the backend, run
> `pip install -r requirements-dev.txt` (adds Tree-sitter, fastembed, FAISS) and
> `alembic upgrade head` (migrations `0002` ingestion, `0003` code analysis,
> `0004` retrieval), then start it again. Re-index existing repositories to build
> their code analysis and search index.

Cloned repositories are stored in `data/repositories/`, search indexes in
`data/indexes/` and downloaded embedding models in `data/models/`, all at the
repository root (configurable with `REPOSITORY_STORAGE_DIR`, `INDEX_STORAGE_DIR`
and `EMBEDDING_CACHE_DIR`). The first indexing run downloads the embedding model
(~100 MB); afterwards it is read from disk. A backend restart interrupts running
indexing jobs; they are marked failed and can simply be started again.

## Tests and checks

```bash
cd backend && source .venv/bin/activate && pytest   # 492 backend tests (no database server, model download or network needed)
scripts/check.sh                                    # ruff + pytest + eslint + typecheck + build
python3 tests/smoke/smoke_test.py                   # while both servers are running
```

See [tests/README.md](tests/README.md) for running backend tests against PostgreSQL.

## Project structure

```
.
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── analysis/        Tree-sitter analyzers, import resolver, dependency graph
│   │   ├── api/v1/          versioned HTTP endpoints (health, projects, repositories, code, search)
│   │   ├── core/            settings, structured logging, errors, middleware
│   │   ├── db/              SQLAlchemy base, sessions, seed data
│   │   ├── ingestion/       URL/path validation, hardened git, storage, scanner, pipeline
│   │   ├── jobs/            background job queue abstraction + handlers
│   │   ├── models/          ORM models: User, Project, Repository, IndexingJob, RepositoryFile,
│   │   │                    CodeFile, CodeSymbol, CodeImport, CodeRelationship,
│   │   │                    CodeChunk, RetrievalLog
│   │   ├── repositories/    data-access layer (Repository pattern)
│   │   ├── retrieval/       chunking, BM25, embeddings, vector store, fusion, rerankers, engine
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── services/        business logic
│   │   └── main.py          application factory
│   ├── alembic/             database migrations (0001 foundation, 0002 ingestion,
│   │                        0003 code analysis, 0004 retrieval)
│   ├── research/            retrieval metrics, benchmark CLI, evaluation query sets
│   ├── tests/               unit, analysis, retrieval, API and migration tests (+ fixture projects)
│   └── requirements.txt     pinned Python dependencies (+ requirements-dev.txt)
├── frontend/                Next.js application
│   └── src/
│       ├── app/             pages (dashboard, repositories, add repository, details, code explorer)
│       ├── components/      layout shell, UI primitives, feature components
│       └── lib/             API client, data-fetching hook, helpers
├── docs/                    architecture, ingestion, code analysis, retrieval, tech stack, development guide
├── scripts/                 setup.sh, check.sh
├── tests/smoke/             end-to-end smoke test for the running app
└── .env.example             every configuration option, documented
```

## API (v1)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/health` | Liveness probe |
| GET | `/api/v1/health/ready` | Readiness probe (checks the database) |
| GET, POST | `/api/v1/projects` | List / create projects |
| GET | `/api/v1/projects/{id}` | Get a project |
| GET | `/api/v1/repositories` | List (filter by `project_id`, `status`) |
| POST | `/api/v1/repositories` | Add a GitHub URL or local path |
| GET | `/api/v1/repositories/{id}` | Metadata, status and latest indexing job |
| POST | `/api/v1/repositories/{id}/index` | Start (re-)indexing in the background — 202 |
| DELETE | `/api/v1/repositories/{id}` | Delete repository, index and checkout — 204 |
| GET | `/api/v1/repositories/{id}/files` | All indexed files, with analysis status |
| GET | `/api/v1/repositories/{id}/files/content?path=` | Source text of a file |
| GET | `/api/v1/repositories/{id}/files/detail?path=` | Symbols, imports, exports, API calls, file dependencies |
| GET | `/api/v1/repositories/{id}/files/symbols?path=` | Symbols of one file |
| GET | `/api/v1/repositories/{id}/symbols?q=&kind=` | Search symbols across the repository |
| GET | `/api/v1/repositories/{id}/dependencies?type=&confidence=&path=&symbol_id=` | Dependency relationships |
| POST | `/api/v1/repositories/{id}/search` | Retrieve relevant chunks (`bm25`, `dense`, `hybrid`, `hybrid_rerank`) |

Example — add, index, and watch a repository:

```bash
API=localhost:8000/api/v1

REPO_ID=$(curl -s -X POST $API/repositories -H 'Content-Type: application/json' \
  -d '{"url": "https://github.com/pallets/markupsafe"}' \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

curl -s -X POST $API/repositories/$REPO_ID/index          # 202 Accepted

curl -s $API/repositories/$REPO_ID | python3 -m json.tool  # repeat until "status": "completed"

curl -s "$API/repositories/$REPO_ID/symbols?q=escape" | python3 -m json.tool
curl -s "$API/repositories/$REPO_ID/dependencies?type=imports&confidence=confirmed" | python3 -m json.tool

curl -s -X POST $API/repositories/$REPO_ID/search -H 'Content-Type: application/json' \
  -d '{"query": "how is html escaped", "top_k": 5, "retrieval_strategy": "hybrid"}' \
  | python3 -m json.tool
```

Optional body fields for `POST /repositories`: `branch`, `name`, `project_id`, and
`"source_type": "local"` with an absolute path as `url` (development only).

## Configuration

The backend reads the repo-root `.env`; see [.env.example](.env.example) for every
option. The frontend needs no configuration by default (it calls
`http://localhost:8000/api/v1`); to change that, set `NEXT_PUBLIC_API_BASE_URL` in
`frontend/.env.local`. Never commit `.env` files.

## Documentation

- [docs/code-analysis.md](docs/code-analysis.md) — Tree-sitter analyzers, extracted data, import resolution, confirmed vs inferred graph
- [docs/retrieval.md](docs/retrieval.md) — chunking, BM25, embeddings, hybrid fusion, reranking, the search API, research logging
- [docs/ingestion.md](docs/ingestion.md) — ingestion pipeline, statuses, security model, background jobs
- [docs/tech-stack.md](docs/tech-stack.md) — every technology used, its version, and what it is for
- [docs/architecture.md](docs/architecture.md) — layers, request lifecycle, data model, error format
- [docs/development.md](docs/development.md) — daily workflow, migrations, adding endpoints, troubleshooting
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision and engineering principles

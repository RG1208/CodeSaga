# CodeSage Architecture

| Phase | Delivered |
| --- | --- |
| 1 — Foundation | Layered FastAPI backend, PostgreSQL + migrations, Next.js shell |
| 2 — Ingestion | Add GitHub/local repositories, background clone → analyze → index, status tracking — see **[ingestion.md](ingestion.md)** |
| 3 — Code analysis | Tree-sitter parsing into symbols, imports and a confirmed/inferred dependency graph; code explorer UI — see **[code-analysis.md](code-analysis.md)** |
| 4 — Retrieval | Code-aware chunking, BM25, BGE embeddings + FAISS, hybrid fusion, reranking, a search endpoint and research logging — see **[retrieval.md](retrieval.md)** |

Retrieval **finds** code; it does not yet answer questions. There is still no LLM
provider, prompt construction, chat interface or code review; those phases build
on the chunks, scores and source locations search returns.

## System overview

```
 Browser ──HTTP──▶ Next.js frontend (:3000)
    │                 renders the app shell; pages fetch data client-side
    │
    └──fetch (CORS)──▶ FastAPI backend (:8000, /api/v1/...)
                          │                    │ enqueue job id
                          │                    ▼
                          │             job worker threads ──git──▶ GitHub (HTTPS)
                          │                    │                     │ shallow clone
                          │  SQLAlchemy        │                     ▼
                          ▼  (psycopg)         ▼             data/repositories/<uuid>/
                       PostgreSQL (:5432) ◀────┘  status, metadata, file index
```

The browser calls the API directly, so the backend owns CORS
(`CORS_ORIGINS`). In development each piece runs as a normal process: PostgreSQL
as a system service, and the backend and frontend in their own terminals (see
the README).

## Backend layers

A request passes through the layers top to bottom; each layer only talks to the
one below it.

| Layer | Package | Responsibility |
| --- | --- | --- |
| API | `app/api/v1/endpoints` | HTTP only: parse and validate input, call a service, shape the response. |
| Dependencies | `app/api/deps.py` | Builds per-request objects (DB session, services, pagination) via FastAPI `Depends`. |
| Services | `app/services` | Business rules (e.g. "a repository must belong to an existing project") and the transaction boundary (`commit`). Raise `AppError` subclasses. |
| Ingestion | `app/ingestion` | Framework-free domain logic: source validation, hardened git client, safe storage, scanner, indexing pipeline. Raises `IngestionError`s, which services map to HTTP errors. |
| Jobs | `app/jobs` | Background job abstraction: `JobQueue` interface, thread/inline queues, named handlers. |
| Analysis | `app/analysis` | Framework-free code analysis: per-language Tree-sitter analyzers behind a `LanguageAnalyzer` interface, an analyzer registry, import resolver and dependency-graph builder. |
| Retrieval | `app/retrieval` | Framework-free search: code-aware chunker, BM25 index, `EmbeddingProvider`/`VectorStore`/`Reranker` interfaces, fusion, composable retriever strategies and the on-disk index store. Raises `RetrievalError`s, which the search service maps to HTTP errors. |
| Repositories | `app/repositories` | Data access (the *Repository pattern*): all SQLAlchemy queries live here. |
| Models | `app/models` | SQLAlchemy ORM tables. |
| Schemas | `app/schemas` | Pydantic request/response models: the public API contract, separate from the tables. |
| Core | `app/core` | Cross-cutting concerns: settings, logging, errors, middleware. |
| DB | `app/db` | Declarative base, engine/session management, seed data. |

> **Naming note:** `app/repositories/` is the data-access layer. The *domain*
> entity for a Git repository is the `Repository` model, so its data-access class
> is `RepositoryRepository`.

Why layers? Endpoints stay thin and testable, business rules have one home, and
swapping storage (or adding a cache) touches only the repository layer — the same
replaceability principle later phases rely on for LLM providers and retrievers.

### Request lifecycle

1. `CORSMiddleware` answers preflight requests and adds CORS headers.
2. `RequestContextMiddleware` assigns a request ID (or accepts a safe
   `X-Request-ID` from the caller), times the request, logs one line when it
   finishes, and converts any unhandled exception into a JSON 500.
3. FastAPI validates path, query and body against the Pydantic schemas.
4. The endpoint calls a service; the service uses repositories and commits.
5. The response is serialised through the endpoint's `response_model`.

### Error handling

All errors share one JSON envelope, and responses carry an `X-Request-ID` header:

```json
{ "error": { "code": "not_found", "message": "Repository … not found.", "details": null, "request_id": "4f…" } }
```

| Source | Status | `code` |
| --- | --- | --- |
| `NotFoundError` raised by a service | 404 | `not_found` |
| `ConflictError` raised by a service | 409 | `conflict`, `repository_exists`, `indexing_in_progress` |
| `ForbiddenError` (e.g. local repositories outside development) | 403 | `local_repositories_disabled` |
| Invalid repository URL/branch/path, repository not found | 422 | `invalid_repository_source`, `repository_not_found`, `branch_not_found`, `empty_repository` |
| GitHub unreachable or too slow | 502 | `network_error`, `git_timeout` |
| Database unique/foreign-key violation (safety net) | 409 | `conflict` |
| Request validation failure | 422 | `validation_error` (field errors in `details`) |
| Unknown route / wrong method | 404 / 405 | `not_found` / `method_not_allowed` |
| Anything unexpected | 500 | `internal_error` (details logged, never returned) |

### Logging

`app/core/logging.py` configures the root logger once. `LOG_FORMAT=json` emits
one JSON object per line (for log aggregation); `console` is a readable
single-line format for development. Every line logged during a request includes
its `request_id`. Extra context is passed with `extra={...}`. Uvicorn's access
log is disabled in favour of the middleware's structured request log, and health
probes are logged at DEBUG to keep the output readable.

### Configuration

`app/core/config.py` defines a Pydantic `Settings` class. Values come from
environment variables, then `backend/.env`, then the repo-root `.env`, then
defaults. Invalid values (e.g. `APP_ENV=moon`) fail at startup.

### API versioning

All routes are mounted under `API_V1_PREFIX` (`/api/v1`) via
`app/api/v1/router.py`. A breaking change would add `app/api/v2/` alongside it.
OpenAPI JSON is served at `/api/v1/openapi.json` and interactive docs at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Liveness: the process is up (no DB access). |
| GET | `/api/v1/health/ready` | Readiness: the database answers; 503 if not. |
| GET | `/api/v1/projects` | List projects (`limit`, `offset`). |
| POST | `/api/v1/projects` | Create a project. |
| GET | `/api/v1/projects/{id}` | Get one project. |
| GET | `/api/v1/repositories` | List repositories (`limit`, `offset`, `project_id`, `status`). |
| POST | `/api/v1/repositories` | Add a GitHub URL or local path (validated, checked with `git ls-remote`). 201. |
| GET | `/api/v1/repositories/{id}` | Repository metadata + `latest_job` (progress). |
| POST | `/api/v1/repositories/{id}/index` | Queue clone → analyze → index → parse. 202 with the job; 409 if one is running. |
| DELETE | `/api/v1/repositories/{id}` | Delete repository, jobs, file index, analysis and checkout. 204; 409 while indexing. |
| GET | `/api/v1/repositories/{id}/files` | Indexed files with analysis status. |
| GET | `/api/v1/repositories/{id}/files/content` | File text (`?path=`), read from the checkout. |
| GET | `/api/v1/repositories/{id}/files/detail` | Symbols, imports, exports, API calls, file dependencies (`?path=`). |
| GET | `/api/v1/repositories/{id}/files/symbols` | Symbols of one file (`?path=`). |
| GET | `/api/v1/repositories/{id}/symbols` | Symbol search (`q`, `kind`, `path_prefix`, `exported`). |
| GET | `/api/v1/repositories/{id}/dependencies` | Relationships (`type`, `confidence`, `path`, `symbol_id`, `direction`). |
| POST | `/api/v1/repositories/{id}/search` | Retrieve chunks (`query`, `top_k`, `retrieval_strategy`, `reranker`, `options`). |

List endpoints return `{ "items": [...], "total", "limit", "offset" }`.

## Data model

```
users 1 ──── * projects 1 ──── * repositories 1 ──┬── * indexing_jobs
                                                  ├── * repository_files
                                                  ├── * code_files 1 ──┬── * code_symbols (tree)
                                                  │                    └── * code_imports
                                                  ├── * code_relationships (file → file, symbol → symbol)
                                                  ├── * code_chunks (→ code_symbols)
                                                  └── * retrieval_logs (detached on delete)
```

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `email` (unique), `full_name`, `is_active` | No credentials yet; authentication is a later phase. |
| `projects` | `name` (unique), `description`, `owner_id` → users | Owner is optional. Repositories added without a project go into `Default`. |
| `repositories` | `project_id`, `name`, `owner`, `url`, `source_type`, `default_branch`, `branch`, `commit_sha`, `local_path`, `status`, `status_message`, `last_indexed_at`, `repo_metadata` (JSON) | Unique per `(project_id, url)`. Deleting a project deletes its repositories. |
| `indexing_jobs` | `repository_id`, `status`, `stage`, `branch`, `commit_sha`, `files_total`, `files_processed`, `error_message`, `started_at`, `finished_at` | One row per indexing run. Partial unique index: one active job per repository. |
| `repository_files` | `repository_id`, `path`, `language`, `size_bytes`, `line_count`, `content_sha256` | The file index. Unique per `(repository_id, path)`. |
| `code_files` | `repository_id`, `path`, `language`, `parse_status`, `symbol_count`, `import_count`, `metadata` | Parsed source files (Python, JS, TS, TSX). |
| `code_symbols` | `file_id`, `parent_symbol_id`, `name`, `qualified_name`, `kind`, `start_line`, `end_line`, `signature`, `docstring`, `return_type`, `parameters`, `decorators`, `metadata` | Functions, methods, classes, components, types. |
| `code_imports` | `file_id`, `module`, `kind`, `names`, `start_line`, `resolution_status`, `resolved_file_id` | One row per import statement. |
| `code_relationships` | `relationship_type`, `confidence`, `source_file_id`, `target_file_id`, `source_symbol_id`, `target_symbol_id`, `weight` | The dependency graph; `confirmed` vs `inferred`. |
| `code_chunks` | `id` (deterministic), `repository_id`, `file_path`, `language`, `chunk_type`, `symbol_id`, `symbol_name`, `symbol_type`, `qualified_name`, `parent_symbol`, `start_line`, `end_line`, `content`, `token_count`, `chunk_metadata` | The retrieval corpus: chunk text and metadata. The index files on disk hold only ids and vectors. |
| `retrieval_logs` | `repository_id` (nullable), `repository_name`, `query`, `strategy`, `reranker`, `top_k`, `options`, `index_info`, `result_chunk_ids`, `results`, `latency_ms`, `timings` | One row per search, for research evaluation. Survives repository deletion. |

All tables use UUID primary keys and `created_at` / `updated_at` timestamps.
Enumerations (`source_type`, repository `status`, job `status`) are stored as
`VARCHAR`, not native PostgreSQL enums, so adding a value later needs no
`ALTER TYPE`. `repo_metadata` is JSON because its shape will grow; anything we
filter on is a real column. Constraint names follow a fixed naming convention
(`app/db/base.py`) so migrations are deterministic.

### Migrations

Alembic (`backend/alembic/`) owns the schema. `env.py` reads `DATABASE_URL` from
settings, so no credentials live in `alembic.ini`. Migrations are applied
explicitly with `alembic upgrade head` (once after setup, and again whenever a
new migration file appears) — the app never changes the schema on startup. Migration
`0003` adds the four code-analysis tables and `0004` the two retrieval tables. A test
(`tests/test_migrations.py`) upgrades an empty database, asserts no drift from
the ORM models, and downgrades again. Migration `0002` also back-fills existing
rows (branch, owner, `ready` → `completed`).

## Frontend

Next.js 16 (App Router) + TypeScript + Tailwind CSS v4.

```
src/
  app/                      routes (server components by default)
    layout.tsx              root layout → <AppShell>
    dashboard/page.tsx
    repositories/page.tsx                  list (live status)
    repositories/new/page.tsx              add repository form
    repositories/[repositoryId]/page.tsx   details, progress, actions, code structure
    repositories/[repositoryId]/code/page.tsx   code explorer
    error.tsx, loading.tsx, not-found.tsx
  components/
    layout/                 app shell, sidebar, header, API status pill
    ui/                     card, badge, button, icons, back link, loading/error/empty states
    dashboard/
    repositories/           table, list, add form, details, indexing progress, language breakdown
    code/                   file tree, source viewer, symbol outline/details, imports panel,
                            dependency diagram (SVG), symbol search, analysis overview
  lib/
    api/client.ts           fetch wrapper → typed results or ApiError
    api/endpoints.ts        one function per backend endpoint
    api/types.ts            TypeScript mirrors of backend schemas
    hooks/use-api.ts        loading / error / success + reload without flicker + cancellation
    hooks/use-interval.ts   polling helper
    repositories.ts         status helpers (active statuses, poll interval, short SHA)
```

- **API client abstraction:** components never call `fetch` directly. They call
  `repositoriesApi.list(...)`, which goes through `apiRequest`, which turns HTTP
  errors, timeouts and network failures into a single `ApiError` type.
- **Loading and error states:** `useApi` returns a discriminated union
  (`loading | success | error`), and the shared `LoadingState`, `ErrorState`
  (with retry and request ID) and `EmptyState` components render each case.
  `app/error.tsx` and `app/loading.tsx` cover route-level failures and transitions.
- **Live progress by polling:** while a repository is `queued`/`cloning`/
  `analyzing`/`indexing`/`parsing`/`embedding`, the list and details pages call `reload()` every 2 s;
  existing data stays on screen during each refresh, and polling stops once the
  status settles.
- Pages are thin server components that render client components for data.

## Running processes

| Process | Command | Port | Reloads on change |
| --- | --- | --- | --- |
| PostgreSQL | system service (`systemctl`, Homebrew, or Windows service) | 5432 | — |
| Backend | `uvicorn app.main:app --reload` (in `backend/`, venv active) | 8000 | Yes (Python files) |
| Frontend | `npm run dev` (in `frontend/`) | 3000 | Yes (Fast Refresh) |

The full inventory of languages, frameworks and libraries — with versions and
what each is used for — is in [tech-stack.md](tech-stack.md).

## Phase boundary

Still out of scope and intentionally absent: authentication, private repositories,
prompt construction, LLM providers, answer generation, the chat interface, code
review and change-impact analysis. Retrieval stops at ranked chunks with their
scores and source locations; `retrieval_logs` and `research/` are where the
evaluation of those answers will start. The disabled "Coming soon" navigation
marks where the chat UI will attach.

# Repository Ingestion (Phase 2)

> Phase 3 added a **parsing** stage to this pipeline ([code-analysis.md](code-analysis.md))
> and Phase 4 an **embedding** stage that builds the search index
> ([retrieval.md](retrieval.md)).

How CodeSage turns a GitHub URL or a local path into a cloned, analyzed and
indexed repository — and how it does so **without ever running repository code**.

Out of scope for this phase: parsing/ASTs, chunking, BM25, embeddings, search,
RAG and code review. Ingestion produces the inputs those phases consume — the
later stages of the same pipeline are documented in their own files.

## The user flow

```
 1. Add          POST /repositories            validate URL/path → git ls-remote → row (status: pending)
 2. Index        POST /repositories/{id}/index create IndexingJob (queued) → hand job id to the queue → 202
 3. Background   worker thread                 clone → analyze → index → completed | failed
 4. Watch        GET  /repositories/{id}       status + latest_job progress (the UI polls every 2 s)
 5. Delete       DELETE /repositories/{id}     rows (cascade) + checkout on disk
```

The API request never clones. Adding a repository only runs `git ls-remote`
(reads refs, downloads no files, 30 s timeout), which gives instant feedback such
as "repository not found" or "branch does not exist".

## Status lifecycle

```
pending ─▶ queued ─▶ cloning ─▶ analyzing ─▶ indexing ─▶ parsing ─▶ embedding ─▶ completed
                        │           │            │           │           │
                        └───────────┴────────────┴───────────┴───────────┴────▶ failed
```

| Status | Meaning |
| --- | --- |
| `pending` | Registered, never indexed. |
| `queued` | Indexing requested; waiting for a free worker. |
| `cloning` | `git clone --depth 1 --single-branch` into a temporary directory. |
| `analyzing` | Walking the checkout: languages, manifests, README/LICENSE, last commit. |
| `indexing` | Reading every indexable file: line count and SHA-256; progress is reported. |
| `parsing` | Tree-sitter analysis of Python/JS/TS/TSX files: symbols, imports, dependency graph; progress is reported. |
| `embedding` | Building the search index: code-aware chunks, BM25, and embeddings when dense retrieval is on; progress is reported per chunk. |
| `completed` | New checkout and search index moved into place; metadata, file index, analysis and chunks saved. |
| `failed` | `status_message` says why; `latest_job.stage` says where. |

`completed` and `failed` can go back to `queued` via re-indexing.

API values are lower-case strings (`"completed"`), matching the rest of the API.

## Pipeline internals (`app/ingestion/indexer.py`)

| Stage | Work | Code |
| --- | --- | --- |
| Clone | Re-validate the stored source, then `GitClient.clone` into `<storage>/.tmp/<id>-<random>`; enforce `MAX_REPOSITORY_SIZE_MB`. | `git.py`, `storage.py` |
| Analyze | `scan_repository`: walk without following symlinks, skip dependency/build folders (`node_modules`, `.git`, `dist`…), count files, detect languages by extension, find manifests, README, LICENSE; enforce `MAX_REPOSITORY_FILES`. `GitClient.last_commit` reads the commit. | `scanner.py`, `languages.py` |
| Index | `index_file` for each file up to `MAX_INDEXED_FILE_SIZE_KB`: skip binaries (NUL byte in the first 8 KB), count lines, hash contents. Progress is written to the job every second. | `scanner.py` |
| Parse | `analyze_repository`: parse supported files, resolve imports, build relationships (see [code-analysis.md](code-analysis.md)). | `app/analysis/` |
| Embed | `build_retrieval_index`: chunk symbols and docs, build BM25, embed chunks into FAISS in a temporary index directory (see [retrieval.md](retrieval.md)). Skipped when `RETRIEVAL_ENABLED=false`. | `app/retrieval/` |
| Complete | Move the temporary checkout into `<storage>/<id>` and the index directory into `<indexes>/<id>`, then in **one transaction** replace the repository's `repository_files`, code-analysis and `code_chunks` rows and set `commit_sha`, `local_path`, `repo_metadata`, `last_indexed_at`, `status=completed`. | `indexer.py` |

**Failure is safe.** All work happens in temporary directories (checkout and
index alike). If any stage fails, they are deleted and the previous successful
index — checkout, search index, commit SHA, metadata and rows — is left
untouched. Error messages
shown to users are written for users; unexpected exceptions are logged with a
traceback and reported only as "Unexpected error while indexing".

### What is stored

| Where | What |
| --- | --- |
| `repositories` | name, owner, canonical URL (or resolved path), default branch, selected branch, **commit SHA**, **local storage path**, status + message, last indexed time, `repo_metadata` (JSON) |
| `repositories.repo_metadata` | total files and bytes, indexed/skipped counts, primary language, per-language files and bytes, manifests, README/LICENSE paths, last commit (SHA, author name, date, subject) |
| `indexing_jobs` | one row per run: status (`queued/running/succeeded/failed`), last stage reached, branch, commit SHA, `files_total` / `files_processed`, error message, start/finish times |
| `repository_files` | one row per indexed text file: path, language, size, line count, SHA-256 |
| `code_chunks` | one row per retrieval chunk: text, location and symbol metadata |
| Disk | `<REPOSITORY_STORAGE_DIR>/<repository-uuid>/` — a shallow git checkout |
| Disk | `<INDEX_STORAGE_DIR>/<repository-uuid>/` — BM25 and vector index files + manifest |

A partial unique index allows at most one `queued`/`running` job per repository,
so two simultaneous "start indexing" clicks cannot both start a job.

## Security

CodeSage **reads** repositories; it never **runs** them.

| Threat | Protection | Where |
| --- | --- | --- |
| Arbitrary URLs (other hosts, `file://`, `ext::` git helpers, SSH, credentials in the URL) | Only `https://github.com/<owner>/<repo>`; owner/repo names checked against GitHub's rules; no ports, query strings, fragments, percent-encoding or extra path segments. `GitClient` independently refuses anything but github.com HTTPS URLs or absolute paths. | `sources.py`, `git.py` |
| Option injection (`--upload-pack=…` as a URL or branch) | Branch names use an allowlist (`A-Z a-z 0-9 . _ / + # @ -`) plus git's ref rules and may not start with `-`; `--` always separates options from URLs/paths. | `sources.py`, `git.py` |
| Shell command injection | git runs via `subprocess.Popen([...])` with an argument list — no shell ever parses user input. | `git.py` |
| Code execution through git (hooks, `core.fsmonitor`, credential helpers, LFS filters, `url.insteadOf`) | Rebuilt environment from an allowlist; `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`; `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c credential.helper= -c submodule.recurse=false`; `GIT_LFS_SKIP_SMUDGE=1`; `GIT_TERMINAL_PROMPT=0`; only the needed protocol is enabled (`protocol.allow=never` + `protocol.https.allow=always`). Local sources use `--no-local` so git's transport is used rather than copying `.git` internals. | `git.py` |
| Malicious symlinks in a repository (e.g. `config -> /etc/passwd`) | Checkouts use `core.symlinks=false` (links become small text files); the scanner never follows symlinks; files are opened with `O_NOFOLLOW`. | `git.py`, `scanner.py` |
| Path traversal on local paths | Must be absolute, no `..`, resolved with symlinks **before** checking it is inside `LOCAL_REPOSITORY_ROOTS`; must be a git working copy. Local sources are refused unless `APP_ENV` is development/test, and re-validated when each job starts. | `sources.py`, `indexer.py` |
| Path traversal on storage | Checkout directories are named by UUID only; every create/replace/delete path is resolved and verified to be inside the storage root; deleting the root itself is refused. | `storage.py` |
| Resource exhaustion | Shallow single-branch clones; clone timeout (whole process group killed); stalled-transfer abort; size, file-count and per-file limits; bounded worker pool. | `git.py`, `indexer.py`, `config.py` |
| Running repository code | Nothing is imported, executed or built. Manifests such as `setup.py` or `package.json` are recorded by **name** only. | `scanner.py` |

The security-relevant behaviour is covered by tests, including a repository whose
hooks and `core.fsmonitor` try to create a marker file during clone
(`tests/unit/test_git_client.py`), URL/branch/path attack strings
(`tests/unit/test_sources.py`) and storage escapes (`tests/unit/test_storage.py`).

## Background jobs (`app/jobs/`)

```
RepositoryService.start_indexing
   │ 1. INSERT indexing_jobs (queued), repository.status = queued, COMMIT
   │ 2. job_queue.enqueue("repositories.index", {"job_id": "<uuid>"})
   ▼
JobQueue ──────────────┬── ThreadJobQueue   (default: ThreadPoolExecutor, JOB_WORKERS threads)
                       ├── InlineJobQueue   (runs immediately; tests/debugging)
                       └── CeleryJobQueue   (future: send_task to a broker)
   ▼
JOB_HANDLERS["repositories.index"](context, payload) → RepositoryIndexer(context).run(job_id)
```

Design rules that make a broker a drop-in replacement:

- **Payloads are plain strings** (the job id), never ORM objects, so they can be
  serialised into a message.
- **The job row is committed before enqueueing**, so a worker in another process
  always finds it.
- **The database is the source of truth** for progress; workers and the API share
  nothing in memory.
- **Handlers are idempotent at the start**: a job that is no longer `queued` is
  skipped, so a redelivered message does nothing.
- **`JobContext`** (settings, session factory, git client, storage, index store,
  embedding provider, reranker registry, cancel event) is built once per worker
  process.

To add Celery later: implement `CeleryJobQueue._submit` with
`celery_app.send_task(name, kwargs=payload)`, register one Celery task that calls
`run_registered_job(name, payload, context, JOB_HANDLERS)`, and set a new
`JOB_BACKEND=celery` in `build_job_queue`. No service, handler or table changes.

### Limits of the thread backend

- Jobs run inside the API process. On shutdown (including `uvicorn --reload`
  restarts) a cancel event stops running clones within about a second; the job is
  marked failed with "Indexing was interrupted…" and can simply be started again.
- On startup, any job still `queued`/`running` from a previous process is marked
  failed, and leftover temporary clones are deleted.
- It assumes **one** API process. Running several uvicorn workers needs a
  broker-backed queue.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `REPOSITORY_STORAGE_DIR` | `data/repositories` (repo root) | Where checkouts live. Keep it outside `backend/`. |
| `RETRIEVAL_ENABLED` | `true` | Whether the embedding stage runs. Retrieval settings: [retrieval.md](retrieval.md). |
| `ALLOW_LOCAL_REPOSITORIES` | `true` | Local paths are additionally limited to development/test. |
| `LOCAL_REPOSITORY_ROOTS` | your home directory | Comma-separated directories local repositories must be inside. |
| `GIT_REMOTE_TIMEOUT_SECONDS` | `30` | `git ls-remote` when adding a repository. |
| `GIT_CLONE_TIMEOUT_SECONDS` | `600` | `git clone` during indexing. |
| `MAX_REPOSITORY_SIZE_MB` | `1024` | Checkout size limit. |
| `MAX_REPOSITORY_FILES` | `100000` | File-count limit. |
| `MAX_INDEXED_FILE_SIZE_KB` | `1024` | Larger files are counted but not indexed. |
| `JOB_BACKEND` | `thread` | `thread` or `inline`. |
| `JOB_WORKERS` | `2` | Repositories indexed concurrently. |

## Known limitations

- Public GitHub repositories only (no tokens, no private repositories, no other hosts).
- One branch per repository record; adding the same URL again in the same project is rejected.
- Shallow clones: only the latest commit is available (history arrives when a later phase needs it).
- No cancel button; a running job finishes, fails, or is interrupted by a restart.
- Every run re-chunks and re-embeds the whole repository; there is no incremental
  update for changed files yet.
- Clone progress is shown as an indeterminate bar (git's own progress output is not parsed).
- Language detection is by file extension.

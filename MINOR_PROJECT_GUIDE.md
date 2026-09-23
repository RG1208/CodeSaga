# CodeSage — what this project is

A tool that reads a GitHub repository and finds the exact code that answers a
plain-English question, with file paths and line numbers.

Example: ask *"how is a signature verified when loading a signed value"* against
`pallets/itsdangerous`, and it returns `signer.py` lines 227–242,
`Signer.verify_signature`.

It does **not** write an answer in words yet — no LLM, no chat box. That is the
next phase. Right now it finds the code; generating the answer comes later.

## How it works

You add a repo → the backend clones it in the background → parses it → builds two
search indexes → you can search it.

```
add repo  →  clone  →  scan files  →  parse with Tree-sitter  →  chunk + index  →  search
             (git)     (languages,    (functions, classes,       (BM25 keyword
                        README)        imports, line numbers)      + BGE vectors)
```

1. **Clone** — shallow `git clone`, hardened so repository code is never executed.
2. **Scan** — languages, manifests, README, line counts, file hashes.
3. **Parse** — Tree-sitter extracts every function, class, method, import and
   export with exact line ranges, plus a dependency graph (imports are
   *confirmed*, calls are *inferred* by name).
4. **Chunk + index** — code is split on symbol boundaries (a chunk = one whole
   function or class), then indexed twice: BM25 for keywords, BGE embeddings in
   FAISS for meaning.
5. **Search** — `POST /api/v1/repositories/{id}/search` with one of four
   strategies.

## The four search strategies

| Strategy | How it matches | Speed |
| --- | --- | --- |
| `bm25` | Keywords, as written | 0.1 ms |
| `dense` | Meaning, via embeddings | 7 ms |
| `hybrid` | Both, combined (default) | 7 ms |
| `hybrid_rerank` | Both, then a neural model re-scores the top 20 | ~1 s |

Why four: BM25 misses paraphrases (it returned the README, not the function),
dense retrieval misses exact identifiers. Measured on a 20-query test set —
dense got Hit@5 **1.00** on paraphrased questions vs BM25's **0.78**; hybrid gave
the best ranking (MRR **0.95**); reranking improved ordering but cost a full
second and did not improve recall.

Reproduce it: `cd backend && .venv/bin/python -m research.benchmark --fixture support_desk`

## Tech stack

| Part | What |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4 |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL (SQLite in-memory for tests) |
| Parsing | Tree-sitter (Python, JS, TS, TSX grammars) |
| Search | NumPy BM25 (own implementation), BGE embeddings via fastembed/ONNX, FAISS, cross-encoder reranker |
| Jobs | Background thread pool inside the API process |
| Testing | pytest (492 tests), Ruff, ESLint |

No Docker — backend and frontend each run in a terminal, PostgreSQL as a local
service.

## What is built (phases 1–4)

1. **Foundation** — layered FastAPI backend, config, migrations, error handling,
   logging, Next.js app shell.
2. **Ingestion** — add a GitHub URL or local path, background clone + scan with
   live progress, re-index, delete. Repository code is never run.
3. **Code analysis** — Tree-sitter symbols, imports, exports, dependency graph,
   and a code explorer UI (file tree, source viewer, symbol outline, diagram).
4. **Retrieval** — chunking, BM25, embeddings, hybrid fusion, reranking, the
   search API, and logging of every search for comparison.

## What is not built yet

- LLM answers and the chat interface (Phase 5)
- AI code review (Phase 6), change-impact analysis (Phase 7)
- Private repos and login; only public GitHub repos work
- Languages other than Python, JS, TS, TSX

## Running it

```bash
# once, after pulling this phase
cd backend && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head          # your DB was still on 0001; this brings it to 0004

# terminal 1
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload

# terminal 2
cd frontend && npm run dev
```

Then open `localhost:3000`. API docs are at `localhost:8000/docs`.

Searching a repo after it finishes indexing:

```bash
curl -s -X POST localhost:8000/api/v1/repositories/<id>/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "how are passwords hashed", "top_k": 5, "retrieval_strategy": "hybrid"}'
```

## Where the details are

| Topic | File |
| --- | --- |
| Retrieval design, chunking, formulas, benchmarks | `docs/retrieval.md` |
| Tree-sitter analysis, what is extracted | `docs/code-analysis.md` |
| Clone pipeline and the security model | `docs/ingestion.md` |
| Layers, data model, request lifecycle | `docs/architecture.md` |
| Every library and version, and why | `docs/tech-stack.md` |
| Daily commands, migrations, troubleshooting | `docs/development.md` |

# Code Retrieval (Phase 4)

How CodeSage finds the code a question is about: code-aware chunking, a BM25
lexical index, dense BGE embeddings, hybrid fusion and optional reranking —
each strategy usable and measurable on its own.

**This phase retrieves; it does not answer.** `POST /repositories/{id}/search`
returns ranked chunks with their scores and source locations. Prompt
construction, LLM answer generation and the chat interface are later phases.

## The four strategies

| Strategy | What it does | Good at | Cost (fixture, this machine) |
| --- | --- | --- | --- |
| `bm25` | Okapi BM25 over code-aware tokens | exact identifiers, error strings, file names | ~0.1 ms |
| `dense` | Cosine similarity over BGE embeddings (FAISS) | paraphrases, "where do we …" questions | ~7 ms |
| `hybrid` | Both, combined by RRF or weighted fusion | the default: neither failure mode alone | ~7 ms |
| `hybrid_rerank` | Hybrid candidates re-scored by a cross-encoder | precision at the very top | ~1 s (CPU) |

Measured on the 20-query fixture set (`research/query_sets/support_desk.json`,
`top_k=5`, BGE-small):

```
strategy          recall@5   precision@5   hit@5     mrr    ndcg@5   p50 ms   p95 ms
bm25                 0.925         0.483   0.950   0.883    0.881     0.07     0.08
dense                1.000         0.475   1.000   0.892    0.916     7.13     8.61
hybrid               0.950         0.446   0.950   0.950    0.950     7.10     8.18
hybrid_rerank        0.925         0.437   0.950   0.900    0.894  1054.94  1083.01
```

Read this as a starting point, not a verdict: 20 queries over 60 chunks is a
smoke test for the machinery. What it does show is the expected split — BM25 is
three orders of magnitude cheaper and unbeatable on literal tokens, dense
retrieval is the only strategy that answers paraphrases (`hit@5` 1.00 vs 0.78 on
the paraphrase half of the set), hybrid gives the best ranking (MRR 0.95), and a
CPU cross-encoder costs a full second without helping on a corpus this small.

Reproduce any of it with:

```bash
cd backend
.venv/bin/python -m research.benchmark --fixture support_desk --top-k 5
```

## Chunking (`app/retrieval/chunking.py`)

Chunks follow the structure Phase 3 already extracted, so a hit is a *symbol*,
not an arbitrary window of characters:

| Chunk type | Produced when |
| --- | --- |
| `symbol` | A function, class, method, interface or component fits in one chunk (the common case). |
| `symbol_header` | A container is too large: its signature and docstring become a chunk, its members are chunked separately. |
| `symbol_part` | A single symbol is still too large: overlapping windows split at blank lines. |
| `module` | Code outside any symbol (imports, constants, module docstring). |
| `section` | A Markdown section, split on headings. |
| `window` | A text file with no structure to follow. |

Blind character splitting is the last resort, never the first: only `symbol_part`
and `window` split, both at blank-line boundaries, with
`CHUNK_OVERLAP_LINES` of overlap so a construct cut in half is still whole in
one of the two chunks. Comment-only gaps between symbols are dropped rather than
indexed as content.

Every chunk carries the metadata a citation needs, in both the database and the
search response:

```
chunk_id          deterministic UUID (see below)
repository_id     which repository
file_path         path inside the repository
language          python | typescript | tsx | javascript | Markdown | …
chunk_type        symbol | symbol_header | symbol_part | module | section | window
symbol_name       decode_token
symbol_type       function | class | method | interface | component | …
qualified_name    TicketService.assign_ticket
parent_symbol     TicketService (null at module level)
start_line        1-based, inclusive
end_line          1-based, inclusive
token_count       BM25 tokens, for cost estimation
```

`start_line`/`end_line` point at the real lines in the checkout, so the UI can
open the file at the hit and the content round-trips exactly
(`tests/api/test_search.py::test_line_numbers_point_at_the_real_source`).

### Deterministic chunk ids

`chunk_id` is a UUID5 of the repository, file path, qualified name, symbol type,
occurrence, part number and a digest of the content. Two consequences that
matter for research:

- Re-indexing an unchanged repository produces **the same chunk ids**, so
  retrieval logs stay comparable across runs.
- Moving a function inside a file does not change its id (line numbers are not
  part of the key), while editing its body does.

## Indexing

The search index is built as the last stage of the ingestion job — the
`embedding` repository status ([ingestion.md](ingestion.md)):

```
parsed files + symbols ─▶ chunks ─▶ BM25 index          (always)
                                 └▶ dense vectors ─▶ FAISS  (when available)
                          chunks ─▶ code_chunks table  (text + metadata)
```

Artifacts live on disk, one directory per repository, written to a temporary
location and renamed into place so a failed build never replaces a working
index:

```
data/indexes/<repository-uuid>/
    manifest.json          what was built, from which commit, with which model
    chunk_ids.json         BM25 document position → chunk id
    bm25.npz               postings, term frequencies, document lengths
    bm25_vocabulary.json
    dense.faiss            vectors (absent when dense indexing is off or failed)
    dense_ids.json
```

`manifest.json` is what makes a stale index detectable: a search refuses an
index built from a different commit (`index_out_of_date`, HTTP 409), and a dense
index built with a different embedding model is ignored rather than mixed with
the configured one (BM25 still answers). Loaded indexes are cached in memory
(four repositories, keyed by build time and embedding model).

**Dense indexing degrades gracefully.** If the embedding model cannot be loaded —
no network on a first run, for example — indexing still completes: BM25 works,
the manifest records `{"status": "unavailable", "reason": …}`, and the
repository page says so. `dense` searches then return 503 while `bm25` keeps
working.

## BM25 (`app/retrieval/bm25.py`)

Okapi BM25 with Lucene's non-negative IDF, ~100 lines of NumPy over an inverted
index, persisted as a compressed `.npz`. Scoring is vectorised over the postings
of the query terms, so a query touches only the documents that contain them.

The tokenizer (`app/retrieval/tokenizer.py`) is the part that makes it work on
code: it splits `getUserById` into `get`, `user`, `by`, `id` **and** keeps
`getuserbyid`, so both "get user by id" and a paste of the identifier match.
Digits stay attached (`pbkdf2` survives), paths contribute their segments, a
light suffix stemmer folds plurals, and 84 stopwords are dropped. `k1` (term
frequency saturation) and `b` (length normalisation) are configurable and
recorded in the manifest.

## Dense retrieval

Three replaceable interfaces:

| Interface | Default | Alternatives |
| --- | --- | --- |
| `EmbeddingProvider` | `FastEmbedProvider` — BGE through ONNX Runtime, CPU-only | `HashingEmbeddingProvider` (offline, deterministic, used by tests); an API-backed provider |
| `VectorStore` | `FaissVectorStore` — `IndexFlatIP` over L2-normalised vectors (exact cosine) | pgvector, or a FAISS approximate index for large corpora |
| `Reranker` | `CrossEncoderReranker` — ms-marco MiniLM through fastembed | any hosted reranker |

The model is named **once**, in configuration (`EMBEDDING_MODEL`), and reaches
the rest of the application only through the provider — nothing else knows
which model is in use, and the manifest records it so a model change invalidates
the dense index instead of silently comparing incompatible vectors.

BGE's recommended query instruction is applied on the query side only
(`EMBEDDING_QUERY_PREFIX`); documents are embedded verbatim, truncated to
`EMBEDDING_MAX_CHARS` because text beyond the model's window is ignored anyway.
Embedding is the slow part of indexing (~1,300 tokens/s on this machine, so
roughly 5 chunks/s), which is why it reports progress and can be cancelled.

## Hybrid fusion (`app/retrieval/fusion.py`)

Both retrievers return `HYBRID_CANDIDATES` results, which are then combined by
one of two configurable methods:

- **`rrf`** (default) — reciprocal rank fusion: `Σ weight / (rrf_k + rank)`.
  Uses only ranks, so it needs no score calibration between a BM25 score of 13
  and a cosine similarity of 0.7. `rrf_k` (default 60) controls how much weight
  the head of each list gets.
- **`weighted`** — min-max normalise each list, then `Σ weight × score`. Keeps
  score magnitudes, at the cost of being sensitive to outliers.

Weights are per request, so `{"fusion_method": "weighted", "bm25_weight": 1,
"dense_weight": 0}` reproduces pure BM25 through the hybrid path — which is how
the tests prove the fusion weights actually do something.

## Reranking

`hybrid_rerank` takes the top `RERANK_CANDIDATES` (default 20) hybrid results
and re-scores each one against the query with a cross-encoder, which reads query
and document *together* instead of comparing two independent vectors. The
first-stage score and rank are kept in the response (`first_stage_score`,
`first_stage_rank`) so the effect of reranking is visible rather than hidden.

Rerankers are named and registered (`RerankerRegistry`), so a request can pick
one (`"reranker": "cross_encoder"`). An unknown name is a 422 listing what is
available; a configured-but-unloadable model is a 503. Nothing silently falls
back to an unreranked list.

On CPU, reranking 20 candidates costs about a second — real, and by far the most
expensive thing in this phase. Reduce `RERANK_CANDIDATES`, or leave reranking
off, if latency matters more than top-1 precision.

## The API

```http
POST /api/v1/repositories/{repository_id}/search
{
  "query": "how are passwords hashed",
  "top_k": 10,
  "retrieval_strategy": "hybrid",        // bm25 | dense | hybrid | hybrid_rerank
  "reranker": null,                       // defaults to the configured one
  "include_content": true,
  "log": null,                            // defaults to RETRIEVAL_LOGGING_ENABLED
  "options": {                            // all optional per-request overrides
    "fusion_method": "rrf",
    "bm25_weight": 0.5,
    "dense_weight": 0.5,
    "rrf_k": 60,
    "candidates": 50,
    "rerank_candidates": 20
  }
}
```

```jsonc
{
  "query": "how are passwords hashed",
  "retrieval_strategy": "hybrid",
  "reranker": null,
  "top_k": 10,
  "result_count": 10,
  "latency_ms": 12.41,
  "timings": { "tokenize_ms": 0.04, "embed_query_ms": 6.2, "bm25_ms": 0.1,
               "dense_ms": 0.3, "fusion_ms": 0.1, "total_ms": 6.9 },
  "options": { "fusion_method": "rrf", "bm25_weight": 0.5, "...": "..." },
  "index": { "commit_sha": "…", "chunk_count": 60, "bm25_terms": 528,
             "dense_available": true, "embedding_model": "BAAI/bge-small-en-v1.5" },
  "results": [
    {
      "rank": 1,
      "score": 0.0328,                    // score of the strategy that ranked it
      "scores": { "bm25": 13.67, "bm25_rank": 1, "dense": 0.72, "dense_rank": 3 },
      "chunk": {
        "chunk_id": "…", "file_path": "app/auth/passwords.py", "language": "python",
        "chunk_type": "symbol", "symbol_name": "hash_password", "symbol_type": "function",
        "qualified_name": "hash_password", "parent_symbol": null,
        "start_line": 18, "end_line": 34, "token_count": 96, "content": "def hash_password(…"
      }
    }
  ],
  "log_id": "…"
}
```

Failure modes are explicit: 404 unknown repository, 409 `repository_not_indexed`
/ `index_not_built` / `index_out_of_date` / `dense_index_unavailable`, 422
invalid request or `unknown_reranker`, 503 `embedding_unavailable` /
`reranker_unavailable`.

## Research logging

Every search is recorded in `retrieval_logs` (unless `"log": false`, or
`RETRIEVAL_LOGGING_ENABLED=false`): query, strategy, reranker, `top_k`, the
effective options, index info (commit and model), the ordered chunk ids, each
result's rank, score, score components and file path, the total latency and the
per-phase timings.

Two deliberate choices make the table usable months later: the options are
stored **flat and named exactly like the request**, so a logged run can be
replayed verbatim; and deleting a repository detaches its logs
(`repository_id` becomes null, the name is kept) instead of cascading them away.

The same metrics the benchmark prints are in `research/metrics.py` — recall@k,
precision@k, hit@k, MRR, nDCG@k and latency percentiles, computed at **file**
level so a query set stays valid when chunking changes.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `RETRIEVAL_ENABLED` | `true` | Build search indexes during indexing at all. |
| `INDEX_STORAGE_DIR` | `data/indexes` | Where index directories live. |
| `CHUNK_MAX_LINES` / `CHUNK_MAX_CHARS` | `60` / `4000` | When a symbol is too large for one chunk. |
| `CHUNK_OVERLAP_LINES` | `8` | Overlap when a symbol must be split. |
| `CHUNK_MIN_LINES` | `2` | Fragments smaller than this are not chunked. |
| `BM25_K1` / `BM25_B` | `1.2` / `0.75` | Term-frequency saturation / length normalisation. |
| `DENSE_RETRIEVAL_ENABLED` | `true` | Embed chunks and build the FAISS index. |
| `EMBEDDING_PROVIDER` | `fastembed` | `fastembed` (local ONNX BGE) or `hashing` (offline). |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Any fastembed-supported model (`bge-base-en-v1.5` for more quality). |
| `EMBEDDING_BATCH_SIZE` / `EMBEDDING_THREADS` | `16` / all cores | Indexing throughput knobs. |
| `EMBEDDING_QUERY_PREFIX` | BGE instruction | Applied to queries only. |
| `EMBEDDING_MAX_CHARS` | `2000` | Per-chunk truncation before embedding. |
| `EMBEDDING_CACHE_DIR` | `data/models` | Downloaded models (~100 MB for BGE-small). |
| `MAX_EMBEDDED_CHUNKS` | `20000` | Cap per repository; the rest stay BM25-only. |
| `VECTOR_STORE` | `faiss` | Vector backend. |
| `HYBRID_FUSION` | `rrf` | `rrf` or `weighted`. |
| `HYBRID_BM25_WEIGHT` / `HYBRID_DENSE_WEIGHT` | `0.5` / `0.5` | Fusion weights. |
| `HYBRID_RRF_K` | `60` | RRF constant. |
| `HYBRID_CANDIDATES` | `50` | Depth of each retriever before fusion. |
| `RERANKER_PROVIDER` | `cross_encoder` | `cross_encoder` or `none`. |
| `RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-encoder model. |
| `RERANK_CANDIDATES` | `20` | How many candidates are re-scored. |
| `RERANK_MAX_CHARS` | `1200` | Per-candidate truncation before reranking. |
| `RETRIEVAL_LOGGING_ENABLED` | `true` | Record searches for research. |

## Testing

```bash
cd backend
.venv/bin/pytest tests/retrieval tests/api/test_search.py   # 156 tests, no downloads
REAL_MODEL_TESTS=1 .venv/bin/pytest tests/retrieval/test_real_models.py
```

The default suite uses `HashingEmbeddingProvider` and a keyword reranker, so it
is deterministic and offline. `tests/fixtures/retrieval/support_desk/` is a small
deliberately-structured repository (15 files, 502 lines: Python auth/billing/notifications/
storage/tickets modules, a TypeScript client, a TSX form, Markdown docs) with
one file per concept, so "did retrieval find the right file" has an unambiguous
answer. `tests/retrieval/test_engine.py` runs every strategy over it and asserts
recall and MRR; `tests/api/test_search.py` does the same over HTTP.

The opt-in `test_real_models.py` is the only place the real models run. It checks
what the offline provider cannot: that dense retrieval answers paraphrases
(`hit@5` 1.00 vs BM25's 0.78) and that the cross-encoder reorders candidates.
Run it before changing any embedding or reranking setting.

## Known limitations

- **Full rebuild per index.** Re-indexing re-chunks and re-embeds everything;
  there is no incremental update for changed files yet. Deterministic chunk ids
  are the groundwork for it.
- **Exact vector search.** `IndexFlatIP` scans every vector — fine to tens of
  thousands of chunks, not to millions. An approximate index or pgvector is the
  next step; `VectorStore` exists so that change stays local.
- **Indexes are local files.** They live on the API host's disk, so several API
  processes cannot share them. Moving to pgvector or object storage removes that.
- **CPU-only models.** BGE-small and the MiniLM cross-encoder are chosen for a
  laptop. Reranking 20 candidates takes ~1 s.
- **English-oriented models.** Identifiers and English prose work; other natural
  languages are untested.
- **Chunk-level scores only.** No file-level aggregation, no deduplication of
  near-identical chunks, no query expansion.
- **Small evaluation set.** 20 queries over 60 chunks. Real conclusions need a
  query set built on a real repository — which is what `research/benchmark.py`
  and the retrieval logs are for.

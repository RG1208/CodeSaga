"""Code retrieval: chunking, lexical (BM25) and dense (vector) search, fusion, reranking.

Each retrieval strategy is a `Retriever` with the same interface, so any of them can be
measured independently (see `backend/research/`):

    bm25          lexical    BM25 over code-aware tokens
    dense         semantic   BGE embeddings in a FAISS index
    hybrid        both       BM25 + dense combined by reciprocal-rank or weighted fusion
    hybrid_rerank both       hybrid candidates re-scored by a cross-encoder

Everything replaceable is behind an interface: `EmbeddingProvider` (fastembed/hashing,
sentence-transformers later), `VectorStore` (FAISS now, pgvector later) and `Reranker`.
No LLM or answer generation lives here — this phase only finds relevant code.
"""

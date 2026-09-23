                         ┌───────────────────┐
                         │     Developer     │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │   React / Next.js │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │      FastAPI      │
                         └─────────┬─────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
       Repository             Code Intelligence       AI Layer
        Manager                   Engine                 │
             │                     │                     │
             ▼              ┌──────┴──────┐       ┌──────┴──────┐
        GitHub/Local        │             │       │             │
                         Tree-sitter   Dependency  RAG          LLM
                             │          Graph       │
                             │             │        │
                             └──────┬──────┘        │
                                    ▼                │
                              Code Chunks            │
                                    │                │
                       ┌────────────┴────────────┐   │
                       ▼                         ▼   │
                     BM25                    BGE/FAISS
                       │                         │
                       └────────────┬────────────┘
                                    ▼
                              Hybrid Retrieval
                                    │
                                    ▼
                                 Reranker
                                    │
                                    ▼
                                    LLM
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                ▼
                Chat          Code Review       Impact Analysis
                   │                │                │
                   └────────────────┼────────────────┘
                                    ▼
                               PostgreSQL
                                    │
                                    ▼
                            Research Evaluation
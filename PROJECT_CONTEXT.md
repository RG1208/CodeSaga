# CodeSage — Project Context

We are building **CodeSage: An AI-Powered Codebase Intelligence and Review Platform**.

The goal is to build a developer tool similar in concept to an AI coding assistant, but focused specifically on **understanding, analyzing, searching, reviewing, and explaining an existing software repository**.

The system should be capable of:

1. Ingesting GitHub repositories or local repositories.
2. Understanding source code structure.
3. Parsing code into ASTs.
4. Extracting functions, classes, imports, exports, APIs, and relationships.
5. Building a code dependency graph.
6. Creating lexical and semantic indexes.
7. Using BM25 + dense vector retrieval + optional reranking.
8. Providing RAG-based conversational codebase understanding.
9. Answering questions with exact source/file references.
10. Explaining functions, classes, files, and workflows.
11. Performing AI-assisted code review.
12. Performing dependency and change-impact analysis.
13. Generating documentation and tests.
14. Providing repository analytics.
15. Evaluating different retrieval strategies scientifically.

## Target Stack

Frontend:

* React / Next.js
* TypeScript
* Tailwind CSS

Backend:

* Python
* FastAPI

Database:

* PostgreSQL

AI / Retrieval:

* LLM provider abstraction
* BGE embeddings
* FAISS initially, with architecture allowing Chroma/pgvector later
* BM25
* Reranker
* RAG

Code Intelligence:

* Tree-sitter
* AST analysis
* dependency graph

Infrastructure:

* Docker
* Docker Compose
* Git
* GitHub API
* CI/CD where appropriate

## Important Engineering Principles

1. Prefer simple, modular architecture.
2. Do not over-engineer prematurely.
3. Every phase must leave the project runnable.
4. Do not rewrite working components unnecessarily.
5. Use environment variables for secrets.
6. Never hardcode API keys.
7. Use proper error handling.
8. Use type hints.
9. Write tests for important backend functionality.
10. Keep AI providers replaceable through abstractions.
11. Keep retrieval components replaceable.
12. Keep the research/evaluation pipeline separate from production application logic.
13. Every AI-generated answer should retain source metadata.
14. Do not blindly trust LLM-generated code. Verify implementations with tests.
15. Do not add unnecessary dependencies.

## Research Direction

A major research component of CodeSage will investigate:

"How do different code retrieval strategies affect LLM-based understanding of software repositories?"

We will eventually compare:

* BM25
* Dense vector retrieval
* Hybrid retrieval
* Hybrid retrieval + reranking

Metrics may include:

* Recall@K
* Precision@K
* MRR
* nDCG
* answer correctness
* faithfulness
* latency
* token usage

The research system must therefore preserve retrieval results and evaluation data.

## Development Rule

Work phase-by-phase.

Do not implement future phases unless explicitly requested.

Before changing existing code:

1. Inspect the repository.
2. Understand the existing architecture.
3. Reuse existing abstractions where appropriate.
4. Explain what will change.
5. Implement.
6. Run tests.
7. Fix failures.
8. Provide a concise summary of files changed and how to verify the result.

The project should remain understandable to a B.Tech student who needs to explain the architecture in a viva and technical interview.

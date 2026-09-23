"""BM25 lexical retrieval over code chunks.

BM25 ranks a document by how often the query's terms appear in it (term frequency),
how rare those terms are across the corpus (inverse document frequency) and how long
the document is (so a long file does not win just by being long).

    score(q, d) = Σ_t  idf(t) · f(t,d)·(k1+1) / ( f(t,d) + k1·(1 - b + b·|d|/avgdl) )

Implemented here rather than taken from a library: it is ~100 lines, keeps the
code-aware tokenizer and the index format under our control, and can be saved next to
the dense index so both are rebuilt together.
"""

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.retrieval.tokenizer import TOKENIZER_VERSION

BM25_FILENAME = "bm25.npz"
BM25_VOCAB_FILENAME = "bm25_vocabulary.json"


@dataclass(frozen=True)
class BM25Params:
    k1: float = 1.2
    b: float = 0.75
    tokenizer_version: int = TOKENIZER_VERSION

    def to_dict(self) -> dict[str, float | int]:
        return {"k1": self.k1, "b": self.b, "tokenizer_version": self.tokenizer_version}


class BM25Index:
    """An inverted index plus the statistics BM25 needs. Search is vectorised with numpy."""

    def __init__(
        self,
        vocabulary: dict[str, int],
        offsets: np.ndarray,
        doc_indices: np.ndarray,
        term_freqs: np.ndarray,
        doc_lengths: np.ndarray,
        params: BM25Params,
    ) -> None:
        self.vocabulary = vocabulary
        self.offsets = offsets  # postings for term i are [offsets[i]:offsets[i+1]]
        self.doc_indices = doc_indices
        self.term_freqs = term_freqs
        self.doc_lengths = doc_lengths
        self.params = params
        self.document_count = int(doc_lengths.shape[0])
        self.average_length = float(doc_lengths.mean()) if self.document_count else 0.0
        # Lucene's non-negative IDF variant.
        document_frequencies = np.diff(offsets).astype(np.float64)
        self._idf = np.log(
            1.0 + (self.document_count - document_frequencies + 0.5) / (document_frequencies + 0.5)
        )

    # -- building ----------------------------------------------------------------

    @classmethod
    def build(
        cls, documents: Sequence[Sequence[str]], params: BM25Params | None = None
    ) -> "BM25Index":
        params = params or BM25Params()
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        doc_lengths = np.zeros(len(documents), dtype=np.float32)
        for index, tokens in enumerate(documents):
            doc_lengths[index] = len(tokens)
            counts: dict[str, int] = defaultdict(int)
            for token in tokens:
                counts[token] += 1
            for token, count in counts.items():
                postings[token].append((index, count))

        vocabulary = {term: position for position, term in enumerate(sorted(postings))}
        offsets = np.zeros(len(vocabulary) + 1, dtype=np.int64)
        doc_indices = np.zeros(sum(len(items) for items in postings.values()), dtype=np.int32)
        term_freqs = np.zeros(doc_indices.shape[0], dtype=np.float32)
        cursor = 0
        for term, position in vocabulary.items():
            offsets[position] = cursor
            for document_index, frequency in postings[term]:
                doc_indices[cursor] = document_index
                term_freqs[cursor] = frequency
                cursor += 1
        offsets[len(vocabulary)] = cursor
        return cls(vocabulary, offsets, doc_indices, term_freqs, doc_lengths, params)

    # -- search ------------------------------------------------------------------

    def score(self, query_tokens: Sequence[str]) -> np.ndarray:
        scores = np.zeros(self.document_count, dtype=np.float32)
        if not self.document_count or self.average_length == 0:
            return scores
        k1, b = self.params.k1, self.params.b
        for token in dict.fromkeys(query_tokens):  # a repeated query term adds nothing
            position = self.vocabulary.get(token)
            if position is None:
                continue
            start, end = self.offsets[position], self.offsets[position + 1]
            documents = self.doc_indices[start:end]
            frequencies = self.term_freqs[start:end]
            normalisation = k1 * (1.0 - b + b * self.doc_lengths[documents] / self.average_length)
            scores[documents] += (
                self._idf[position] * frequencies * (k1 + 1.0) / (frequencies + normalisation)
            )
        return scores

    def search(self, query_tokens: Sequence[str], top_k: int) -> list[tuple[int, float]]:
        """Best `top_k` documents as (document index, score), highest first."""
        scores = self.score(query_tokens)
        if not scores.size:
            return []
        count = min(top_k, int((scores > 0).sum()))
        if count == 0:
            return []
        candidates = np.argpartition(-scores, count - 1)[:count]
        ordered = candidates[np.argsort(-scores[candidates], kind="stable")]
        return [(int(index), float(scores[index])) for index in ordered]

    # -- persistence --------------------------------------------------------------

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez(
            directory / BM25_FILENAME,
            offsets=self.offsets,
            doc_indices=self.doc_indices,
            term_freqs=self.term_freqs,
            doc_lengths=self.doc_lengths,
        )
        (directory / BM25_VOCAB_FILENAME).write_text(
            json.dumps({"terms": list(self.vocabulary), "params": self.params.to_dict()}),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> "BM25Index":
        with np.load(directory / BM25_FILENAME, allow_pickle=False) as arrays:
            offsets = arrays["offsets"]
            doc_indices = arrays["doc_indices"]
            term_freqs = arrays["term_freqs"]
            doc_lengths = arrays["doc_lengths"]
        payload = json.loads((directory / BM25_VOCAB_FILENAME).read_text(encoding="utf-8"))
        vocabulary = {term: position for position, term in enumerate(payload["terms"])}
        params = BM25Params(**payload["params"])
        return cls(vocabulary, offsets, doc_indices, term_freqs, doc_lengths, params)

    @property
    def term_count(self) -> int:
        return len(self.vocabulary)

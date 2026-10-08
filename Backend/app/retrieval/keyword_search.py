"""Keyword search (BM25). Implemented from scratch in pure Python rather
than adding a dependency (e.g. rank-bm25) — the algorithm is small
enough that owning it directly means no risk of an unpinned third-party
package changing behavior under us, and it keeps this module runnable
in any environment without a network-installed extra.

Why BM25 alongside embeddings at all: embedding similarity is good at
"what is this about" but often loses exact tokens — a name, a formula
number, a specific figure/equation reference — that a lexical match
finds trivially. "What is equation 3?" should find the chunk containing
the literal text "Equation 3" even if that chunk's embedding isn't the
closest match to the question's embedding. This is exactly the failure
mode hybrid search (BM25 + embeddings, fused) is for.
"""

import math
import re
from dataclasses import dataclass, field

from ..domain.citations import build_citation
from ..domain.entities import DocumentChunk
from .models import RetrievedChunk

# Unicode-aware tokenizer: \w matches Arabic letters as well as Latin
# under Python's default UNICODE regex flag, so this needs no separate
# Arabic-specific path. Numbers are kept as their own tokens (not
# stripped) since exact numbers are one of BM25's main jobs here
# ("equation 3", "table 4.2").
_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)

# BM25 standard parameters (Robertson/Sparck Jones). k1 controls term-
# frequency saturation, b controls document-length normalization
# strength — these are the conventional defaults used by, e.g.,
# Elasticsearch/Lucene's BM25 similarity, not tuned specifically for this
# corpus.
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class KeywordIndex:
    """A built BM25 index over one chat's chunks. `chunks` and
    `tokenized_docs` are parallel lists — `chunks[i]`'s tokens are
    `tokenized_docs[i]`."""

    chunks: list[DocumentChunk]
    tokenized_docs: list[list[str]]
    doc_freq: dict[str, int]  # term -> number of docs containing it
    idf: dict[str, float]
    doc_lengths: list[int]
    avg_doc_length: float
    fingerprint: tuple = field(repr=False)


def _fingerprint(chunks: list[DocumentChunk]) -> tuple:
    """Cheap signature of "which chunks, in what order" — used to detect
    when a chat's chunk set has changed (re-uploaded document) without
    re-tokenizing every chunk just to check. Falls back to id(chunk) for
    any chunk without a DB id yet (shouldn't normally happen at query
    time, but keeps this safe rather than raising)."""
    return tuple(c.id if c.id is not None else id(c) for c in chunks)


def build_keyword_index(chunks: list[DocumentChunk]) -> KeywordIndex:
    tokenized_docs = [tokenize(c.text) for c in chunks]
    doc_lengths = [len(toks) for toks in tokenized_docs]
    avg_doc_length = (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 0.0

    doc_freq: dict[str, int] = {}
    for toks in tokenized_docs:
        for term in set(toks):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    n_docs = len(chunks)
    idf: dict[str, float] = {}
    for term, df in doc_freq.items():
        # BM25's standard IDF, floored at a small positive epsilon so a
        # term appearing in every single chunk never goes negative and
        # start actively *penalizing* documents that contain it.
        idf[term] = max(math.log((n_docs - df + 0.5) / (df + 0.5) + 1), 1e-9)

    return KeywordIndex(
        chunks=chunks,
        tokenized_docs=tokenized_docs,
        doc_freq=doc_freq,
        idf=idf,
        doc_lengths=doc_lengths,
        avg_doc_length=avg_doc_length,
        fingerprint=_fingerprint(chunks),
    )


def _bm25_score(query_terms: list[str], doc_index: int, index: KeywordIndex) -> float:
    doc_tokens = index.tokenized_docs[doc_index]
    if not doc_tokens:
        return 0.0

    term_counts: dict[str, int] = {}
    for t in doc_tokens:
        term_counts[t] = term_counts.get(t, 0) + 1

    doc_len = index.doc_lengths[doc_index]
    avg_len = index.avg_doc_length or 1.0

    score = 0.0
    for term in query_terms:
        tf = term_counts.get(term, 0)
        if tf == 0:
            continue
        idf = index.idf.get(term, 0.0)
        numerator = tf * (K1 + 1)
        denominator = tf + K1 * (1 - B + B * (doc_len / avg_len))
        score += idf * (numerator / denominator)
    return score


def search_keyword(index: KeywordIndex, query: str, top_k: int = 8) -> list[RetrievedChunk]:
    query_terms = tokenize(query)
    if not query_terms or not index.chunks:
        return []

    scored: list[tuple[int, float]] = []
    for i in range(len(index.chunks)):
        score = _bm25_score(query_terms, i, index)
        if score > 0:
            scored.append((i, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    scored = scored[:top_k]

    # Normalize to 0..1 by the batch's own max score so keyword_score is
    # comparable across queries in logs/UI — RRF fusion itself is
    # rank-based and doesn't need this, but reranking and any future
    # score-display code benefits from a bounded scale.
    max_score = scored[0][1] if scored else 1.0

    results = []
    for i, raw_score in scored:
        c = index.chunks[i]
        normalized = raw_score / max_score if max_score > 0 else 0.0
        results.append(
            RetrievedChunk(
                chunk_id=c.id,
                text=c.text,
                score=normalized,
                semantic_score=0.0,
                keyword_score=normalized,
                page=c.page,
                chapter=c.chapter,
                section=c.section,
                heading=c.heading,
                citation=build_citation(c),
                document_id=c.document_id,
                chunk=c,
            )
        )
    return results


class KeywordIndexCache:
    """In-memory cache of one `KeywordIndex` per chat. Rebuilds only when
    a chat's chunk fingerprint changes (new upload / replaced document)
    — the common case, repeated questions against the same document,
    never re-tokenizes. Not persisted across process restarts, same as
    `InMemoryVectorStore` — rebuilding on cold start is cheap relative
    to a full document re-parse."""

    def __init__(self):
        self._cache: dict[int, KeywordIndex] = {}

    def get_or_build(self, chat_id: int, chunks: list[DocumentChunk]) -> KeywordIndex:
        fingerprint = _fingerprint(chunks)
        cached = self._cache.get(chat_id)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached

        index = build_keyword_index(chunks)
        self._cache[chat_id] = index
        return index

    def invalidate(self, chat_id: int) -> None:
        self._cache.pop(chat_id, None)

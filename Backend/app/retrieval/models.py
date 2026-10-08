"""Shared data models for the Phase 3 hybrid retrieval pipeline.

`RetrievedChunk` is the "structured result" spec item 9 asks for — one
per candidate chunk, carrying both individual method scores (semantic,
keyword) and the fused/reranked score, plus everything needed to cite it
(chapter/section/heading/physical page) without a second lookup. It
also carries a `chunk` back-reference to the full `DocumentChunk` — an
addition beyond the spec's literal field list, kept because
context-expansion and prompt-building already work in terms of full
`DocumentChunk` objects (by `.id`, `.text`, `.bbox`, etc.), and
duplicating that plumbing for a leaner struct isn't worth the risk of
drift between two representations of "the same chunk".

This module deliberately has zero dependency on any retrieval
*algorithm* (BM25, embeddings, RRF) — those live in their own modules
and import these types, not the other way around.
"""

from dataclasses import dataclass, field

from ..domain.citations import Citation
from ..domain.entities import DocumentChunk


@dataclass
class RetrievedChunk:
    chunk_id: int | str | None
    text: str
    score: float  # final combined score used for ordering (see RerankWeights)
    semantic_score: float  # 0.0 if this chunk wasn't found by semantic search
    keyword_score: float  # 0.0 if this chunk wasn't found by keyword search
    page: int  # physical page — the only page field citations are ever built from (see domain/citations.py)
    chapter: str | None
    section: str | None
    heading: str | None
    citation: Citation
    document_id: str | None = None
    chunk: DocumentChunk | None = field(default=None, repr=False)
    rerank_score: float = 0.0  # 0.0 until a BaseReranker has scored this candidate (Phase 4)


@dataclass
class QueryAnalysis:
    """The output of the 'Query Understanding' pipeline stage. Populated
    once per question and threaded through semantic search, keyword
    search, filtering, and reranking so each stage sees the same
    interpretation of the query rather than re-deriving it."""

    raw_question: str
    intent: str  # 'explain' | 'specific' — reuses query_understanding.classify_intent
    keywords: list[str]
    numbers: list[str]
    page_references: list[int]
    chapter_hint: str | None
    section_hint: str | None


@dataclass
class RetrievalFilters:
    """Metadata filters applied before search narrows the candidate pool.
    All fields are optional matchers — None means "don't filter on
    this". String fields match case-insensitively as substrings (chunk
    metadata is free text extracted by the hierarchy detector, not a
    controlled vocabulary, so exact equality would miss too much —
    e.g. chunk.chapter == "Chapter 3: Neural Networks" vs a filter hint
    of "chapter 3")."""

    document_id: str | None = None
    chapter: str | None = None
    section: str | None = None
    page: int | None = None  # physical page only — filtering by a printed page label is not supported

    def is_empty(self) -> bool:
        return not any((self.document_id, self.chapter, self.section, self.page))


@dataclass
class RerankWeights:
    """Weights for the Phase 4 final-score formula:

        final_score = semantic_weight * semantic_score
                     + keyword_weight  * keyword_score
                     + rerank_weight   * rerank_score

    Defaults match the spec's own example. Not required to sum to 1.0 —
    kept as independent knobs rather than a normalized mix so a
    deployment can, e.g., turn keyword_weight to 0 without needing to
    rebalance the other two."""

    semantic_weight: float = 0.3
    keyword_weight: float = 0.2
    rerank_weight: float = 0.5

    def combine(self, semantic_score: float, keyword_score: float, rerank_score: float) -> float:
        return (
            self.semantic_weight * semantic_score
            + self.keyword_weight * keyword_score
            + self.rerank_weight * rerank_score
        )

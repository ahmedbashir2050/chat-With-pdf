"""Semantic search stage. Thin wrapper around the existing `VectorStore`
port (unchanged from Phase 1/2) that adapts its output — `ScoredChunk`,
a bare (chunk, score) pair — into the richer `RetrievedChunk` shape the
rest of the Phase 3 pipeline works with.
"""

from ..domain.citations import build_citation
from ..domain.entities import DocumentChunk
from ..domain.interfaces import VectorStore
from .models import RetrievedChunk


class SemanticSearchService:
    def __init__(self, vector_store: VectorStore):
        self._vector_store = vector_store

    def search(
        self,
        chunks: list[DocumentChunk],
        query_embedding: list[float],
        top_k: int = 8,
        similarity_threshold: float = 0.0,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """`document_id` filters the candidate pool before scoring — kept
        as a direct parameter (rather than requiring the caller to
        pre-filter `chunks`) since it's the one filter cheap enough to
        push down to this stage without duplicating `filters.py`'s more
        general logic for the common single-document case."""
        pool = chunks if document_id is None else [c for c in chunks if c.document_id == document_id]
        if not pool:
            return []

        scored = self._vector_store.top_k_with_scores(pool, query_embedding, k=top_k)

        results = []
        for sc in scored:
            if sc.score < similarity_threshold:
                continue
            c = sc.chunk
            results.append(
                RetrievedChunk(
                    chunk_id=c.id,
                    text=c.text,
                    score=sc.score,
                    semantic_score=sc.score,
                    keyword_score=0.0,
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

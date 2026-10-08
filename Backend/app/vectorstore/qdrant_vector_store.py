"""Qdrant-backed implementation of `domain.interfaces.VectorStore` — the
one piece the spec asks to replace. Same public method signature as
`InMemoryVectorStore.top_k_with_scores` on purpose: `SemanticSearchService`
(retrieval/semantic_search.py), `HybridSearchService`, and every caller
above them are untouched. Only api/deps.py's composition root changes
which concrete class gets wired in.

Why the signature still takes `chunks` even though Qdrant doesn't need
them to do the search: `SemanticSearchService.search` already narrows
`chunks` down to the chat (and, when given, the single document) being
queried before calling this. Rather than requiring every caller to be
rewritten to pass a `VectorSearchFilter` instead, this adapter derives the
equivalent Qdrant filter (`chat_id`, optionally `document_id`) from the
pool it's handed, so the search Qdrant runs is scoped exactly the same
way the old brute-force scan was — just executed as an HNSW query instead
of a Python loop. `chunks` is also used to translate Qdrant's hits (which
carry only a `chunk_id` and score) back into full `DocumentChunk`/
`ScoredChunk` objects without a second database round trip.
"""

from __future__ import annotations

import logging

from ..domain.entities import DocumentChunk, ScoredChunk
from ..vector.exceptions import VectorDatabaseError
from ..vector.models import VectorSearchFilter
from ..vector.service import QdrantService
from .in_memory_vector_store import InMemoryVectorStore

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Implements domain.interfaces.VectorStore."""

    def __init__(self, service: QdrantService, *, fallback_on_unavailable: bool = True):
        self._service = service
        self._fallback = InMemoryVectorStore() if fallback_on_unavailable else None

    def top_k_with_scores(
        self, chunks: list[DocumentChunk], query_embedding: list[float], k: int = 4
    ) -> list[ScoredChunk]:
        if not chunks:
            return []

        by_id = {c.id: c for c in chunks if c.id is not None}
        if not by_id:
            # Chunks that were never persisted (no id yet) can't be
            # looked up in Qdrant by chunk_id — fall back immediately
            # rather than querying a collection that can't answer.
            return self._brute_force(chunks, query_embedding, k)

        chat_id = chunks[0].chat_id
        document_ids = {c.document_id for c in chunks if c.document_id is not None}
        # Only push document_id into the filter when the whole pool
        # shares one — if the caller passed a mixed-document pool (no
        # document_id filter applied upstream), restricting by chunk_id
        # membership below is still correct without it.
        document_id = next(iter(document_ids)) if len(document_ids) == 1 else None

        vector_filter = VectorSearchFilter(
            chat_id=chat_id,
            document_id=document_id,
            chunk_ids=tuple(by_id.keys()) if document_id is None else None,
        )

        try:
            hits = self._service.search(query_embedding, top_k=k, filters=vector_filter)
        except VectorDatabaseError as exc:
            logger.warning("Qdrant search unavailable, falling back to brute-force cosine search: %s", exc)
            return self._brute_force(chunks, query_embedding, k)

        results = []
        for hit in hits:
            chunk = by_id.get(hit.chunk_id)
            if chunk is None:
                # Point exists in Qdrant but not in the caller's pool
                # (e.g. a stale vector from a chunk deleted in SQLite but
                # not yet cleaned up in Qdrant) — skip rather than
                # surface a chunk the caller didn't ask about.
                continue
            results.append(ScoredChunk(chunk=chunk, score=hit.score))
        return results

    def _brute_force(
        self, chunks: list[DocumentChunk], query_embedding: list[float], k: int
    ) -> list[ScoredChunk]:
        if self._fallback is None:
            return []
        return self._fallback.top_k_with_scores(chunks, query_embedding, k=k)

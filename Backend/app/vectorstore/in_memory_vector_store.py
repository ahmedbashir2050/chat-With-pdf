"""VectorStore implementation. Today this is the exact same brute-force
cosine-similarity approach as the original embedding_utils.py — every
chunk's embedding compared in pure Python, every query. Behavior is
unchanged; what changed is that retrieval logic now depends on the
VectorStore *interface*, not on this specific implementation, so a future
pgvector/FAISS/Qdrant-backed class can be swapped in (Phase 1 finding
§3.4: retrieval doesn't scale past a modest chunk count) without touching
retriever.py or any application-layer code.
"""

import math

from ..domain.entities import DocumentChunk, ScoredChunk


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    """Implements domain.interfaces.VectorStore."""

    def top_k_with_scores(
        self, chunks: list[DocumentChunk], query_embedding: list[float], k: int = 4
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=c, score=cosine_similarity(c.embedding, query_embedding))
            for c in chunks
            if c.embedding is not None
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return scored[:k]

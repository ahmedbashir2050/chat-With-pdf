"""Hybrid search — semantic + keyword search fused via Reciprocal Rank
Fusion (RRF), producing a wide *candidate* pool. Final selection down to
the handful of chunks actually sent to the LLM is Phase 4's job — see
`RerankerService` (rerank_service.py) — kept as a separate stage
deliberately: RRF's job is cheap, high-recall candidate generation;
reranking's job is precise, more expensive candidate selection. Fusing
them into one step would make it harder to reason about (and tune)
either half independently.

RRF instead of a weighted score blend for the fusion step: cosine
similarity (roughly 0..1, densely packed near the top matches) and BM25
(unbounded, long-tailed) are on incomparable scales, and any fixed blend
weight either drowns one signal out or needs per-corpus tuning. RRF only
uses each list's *rank*, not its score, which is exactly what makes it a
standard, tuning-free way to combine heterogeneous rankers:

    RRF(d) = sum over each ranking r containing d of  1 / (k + rank_r(d))

A chunk ranked #1 by BM25 but missed by semantic search, and a chunk
ranked #1 by semantic search but missed by BM25, both get a meaningful
combined score.
"""

from dataclasses import replace

from ..domain.entities import DocumentChunk
from .filters import apply_metadata_filters
from .keyword_search import KeywordIndexCache, search_keyword
from .models import QueryAnalysis, RetrievalFilters, RetrievedChunk
from .rerank_service import RerankerService
from .semantic_search import SemanticSearchService

# Standard RRF constant (Cormack et al., 2009) — dampens the impact of a
# #1 rank so that agreement between rankers matters more than either
# ranker's single best guess.
RRF_K = 60

# Default candidate-pool size fetched from each of semantic/keyword
# search before fusion+reranking — spec item: "Retrieve top 20-50
# candidates". Configurable per-call (see HybridSearchService.search's
# `candidate_count` param) and, at the composition root, via
# Settings.rerank_candidate_count.
DEFAULT_CANDIDATE_COUNT = 30


def _reciprocal_rank_fusion(
    semantic_results: list[RetrievedChunk], keyword_results: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    by_id: dict[int | str, RetrievedChunk] = {}
    rrf_scores: dict[int | str, float] = {}

    for rank, r in enumerate(semantic_results, start=1):
        key = r.chunk_id
        by_id[key] = r
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + rank)

    for rank, r in enumerate(keyword_results, start=1):
        key = r.chunk_id
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
        if key in by_id:
            # Merge: keep the existing (semantic) result object but carry
            # forward the keyword score it was missing.
            by_id[key] = replace(by_id[key], keyword_score=r.keyword_score)
        else:
            by_id[key] = r

    fused = []
    for key, item in by_id.items():
        fused.append(replace(item, score=rrf_scores[key]))

    fused.sort(key=lambda r: r.score, reverse=True)
    return fused


class HybridSearchService:
    def __init__(
        self,
        semantic_search: SemanticSearchService,
        keyword_index_cache: KeywordIndexCache,
        reranker_service: RerankerService,
    ):
        self._semantic = semantic_search
        self._keyword_cache = keyword_index_cache
        self._reranker_service = reranker_service

    def search(
        self,
        chat_id: int,
        query: str,
        query_embedding: list[float],
        all_chunks: list[DocumentChunk],
        top_k: int = 8,
        filters: RetrievalFilters | None = None,
        analysis: QueryAnalysis | None = None,
        candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    ) -> list[RetrievedChunk]:
        """Question -> query understanding (already done by the caller;
        `analysis`) -> semantic + keyword search -> RRF fusion (this
        stage) -> reranking down to `top_k` (RerankerService) -> back to
        the caller for context expansion. Neighbor expansion itself is
        deliberately NOT done here — it stays the caller's (Retriever's)
        job, since it needs the full unfiltered `all_chunks` in document
        order."""
        pool = apply_metadata_filters(all_chunks, filters)
        if not pool:
            # A filter that matched nothing (e.g. a chapter hint that
            # doesn't line up with how this document's chapters were
            # detected) shouldn't silently produce zero results — fall
            # back to searching the whole document.
            pool = all_chunks

        semantic_results = self._semantic.search(pool, query_embedding, top_k=candidate_count)
        keyword_index = self._keyword_cache.get_or_build(chat_id, all_chunks)
        keyword_results = search_keyword(keyword_index, query, top_k=candidate_count)
        # Keyword results are built from the full chat's index (cached
        # across queries) — filter them down to the same pool semantic
        # search used, for a consistent fused ranking.
        pool_ids = {c.id for c in pool}
        keyword_results = [r for r in keyword_results if r.chunk_id in pool_ids]

        candidates = _reciprocal_rank_fusion(semantic_results, keyword_results)
        return self._reranker_service.rerank(query, candidates, top_k=top_k, analysis=analysis)

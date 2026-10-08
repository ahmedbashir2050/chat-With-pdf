"""RerankerService — the spec's requested `rerank(query, results) ->
results` interface (spec item 1; "results" here is `list[RetrievedChunk]`,
Phase 3's structured per-chunk result — see models.py's docstring for why
it isn't literally named `RetrievalResult`).

This is the one place the final-score formula (spec item 5) lives:

    final_score = semantic_weight * semantic_score
                 + keyword_weight  * keyword_score
                 + rerank_weight   * rerank_score

regardless of which `BaseReranker` produced `rerank_score`. Splitting
"compute rerank_score" (BaseReranker) from "combine scores and select
top_k" (this class) means swapping the reranker provider never risks
touching the weighting logic, and vice versa.
"""

from dataclasses import replace

from .models import QueryAnalysis, RerankWeights, RetrievedChunk
from .reranker import BaseReranker


class RerankerService:
    def __init__(self, reranker: BaseReranker, weights: RerankWeights | None = None):
        self._reranker = reranker
        self._weights = weights or RerankWeights()

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int | None = None,
        analysis: QueryAnalysis | None = None,
    ) -> list[RetrievedChunk]:
        """Returns `candidates` reordered by combined score, sliced to
        `top_k` (or the full list if `top_k` is None). Every original
        score — semantic_score, keyword_score, and now rerank_score — is
        preserved on each returned item (spec item 1); `.score` is
        overwritten with the combined score used for ordering, exactly
        as it already was after RRF fusion in Phase 3. No candidate's
        metadata (chapter/section/heading/page/citation/bbox)
        is touched, since `BaseReranker.score()` only ever writes
        `.rerank_score` — see reranker.py's docstring."""
        if not candidates:
            return []

        self._reranker.score(query, candidates, analysis)

        combined = [
            replace(
                c,
                score=self._weights.combine(c.semantic_score, c.keyword_score, c.rerank_score),
            )
            for c in candidates
        ]
        combined.sort(key=lambda c: c.score, reverse=True)

        return combined[:top_k] if top_k is not None else combined

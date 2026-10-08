"""Retrieval orchestration. This is the logic that used to live directly
inside routers/messages.py's `_handle_rag_question` — extracted so it can
be used (and tested) independently of any HTTP concern.

Phase 3: `retrieve()`'s own logic (query rewriting, intent-based depth,
out-of-scope detection, neighbor expansion) is unchanged; what changed is
*how the candidate chunks are found* — a single vector-store lookup is
now a full hybrid pipeline (query understanding -> semantic + keyword
search -> RRF fusion -> reranking), encapsulated behind
`HybridSearchService.search()`.

Phase 6: the inline classify/rewrite/analyze/filter glue that used to
live directly in this method is now one call to
`QueryUnderstandingService.understand()` (app/query/) — a richer
replacement for the same job, not an algorithm change. RRF fusion and
reranking (`HybridSearchService`, `RerankerService`) are untouched;
`RetrievalResult`'s existing fields keep their exact old meaning
(`.intent` is still the legacy 'explain'/'specific' bucket, since
`prompts.py` and `context/`'s depth logic already key off it), with one
new field — `.plan` — carrying the full Phase 6 `QueryAnalysis` for
anything downstream that wants the richer picture (see
`application/qa_service.py`).
"""

from dataclasses import dataclass

from ..config import settings
from ..domain.entities import DocumentChunk
from ..domain.interfaces import EmbeddingService, LLMService
from ..query.models import QueryAnalysis as RichQueryAnalysis
from ..query.query_analyzer import QueryUnderstandingService
from .context_expander import expand_with_neighbors
from .hybrid_search import HybridSearchService

# Below this cosine-similarity score, the best-matching chunk still isn't
# a real match — it's just the least-irrelevant thing in the document.
# Heuristic, not calibrated — see Phase 1 review §3.3. Checked against
# `semantic_score` specifically (not the fused/reranked `score`, which is
# on an RRF/heuristic-boost scale, not a similarity scale) so this
# threshold's meaning hasn't changed from Phase 1/2.
#
# Moved into Settings (settings.out_of_scope_similarity_threshold) so it's
# tunable via OUT_OF_SCOPE_SIMILARITY_THRESHOLD without a code change —
# this module-level constant is kept ONLY as the default value baked into
# Settings and is no longer read directly below.
OUT_OF_SCOPE_SIMILARITY_THRESHOLD = 0.25


@dataclass
class RetrievalResult:
    chunks: list[DocumentChunk]  # matched chunks + their expanded neighbors — what's sent to the LLM as context
    matched_chunks: list[DocumentChunk]  # the original top-k, before neighbor expansion — what citations are built from
    intent: str  # 'explain' | 'specific' — legacy depth bucket, see module docstring
    is_out_of_scope: bool
    search_query: str  # the (possibly rewritten) query actually used for search
    relevance_by_id: dict = None  # {chunk.id: fused/reranked score} — Phase 5's context_ranker groups by this
    plan: RichQueryAnalysis = None  # Phase 6's full query analysis — answer_style, entities, complexity, etc.


class Retriever:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        llm_service: LLMService,
        hybrid_search: HybridSearchService,
        query_understanding: QueryUnderstandingService,
    ):
        self._embeddings = embedding_service
        self._llm = llm_service
        self._hybrid_search = hybrid_search
        self._query_understanding = query_understanding

    def retrieve(self, chat_id: int, question: str, all_chunks: list[DocumentChunk], history: list[dict]) -> RetrievalResult:
        """Smarter than a bare top-k lookup:
        1. Query understanding (Phase 6) rewrites the query using
           conversation history, classifies intent from a 15-category
           taxonomy, extracts entities, and plans a search strategy —
           all in one call (see app/query/query_analyzer.py).
        2. Retrieval runs hybrid: semantic (embeddings) and keyword
           (BM25) search in parallel, fused via Reciprocal Rank Fusion —
           catches both "what's this about" and "find this exact term"
           queries in one pass, then reranked.
        3. Retrieval depth adapts to intent — explanatory questions pull
           in more supporting context than a quick fact lookup needs.
        4. Retrieved chunks get their immediate neighbors attached, so the
           model isn't reasoning over fragments cut off mid-thought.
        5. If nothing retrieved is actually relevant (see
           OUT_OF_SCOPE_SIMILARITY_THRESHOLD), that's surfaced on the
           result rather than silently returning weak matches — the
           caller decides what to do (see application/qa_service.py).
        """
        analysis, plan = self._query_understanding.understand(chat_id, question, history)
        search_query = analysis.rewritten_query

        k = 8 if plan.depth_bucket == "explain" else 4
        neighbor_window = 1 if plan.depth_bucket == "explain" else 0
        candidate_count = max(1, int(settings.rerank_candidate_count * plan.candidate_count_multiplier))

        query_embedding = self._embeddings.embed_one(search_query)
        retrieved = self._hybrid_search.search(
            chat_id=chat_id,
            query=search_query,
            query_embedding=query_embedding,
            all_chunks=all_chunks,
            top_k=k,
            filters=analysis.filters,
            analysis=analysis,
            candidate_count=candidate_count,
        )

        best_semantic_score = max((r.semantic_score for r in retrieved), default=0.0)
        if not retrieved or best_semantic_score < settings.out_of_scope_similarity_threshold:
            return RetrievalResult(
                chunks=[],
                matched_chunks=[],
                intent=plan.depth_bucket,
                is_out_of_scope=True,
                search_query=search_query,
                relevance_by_id={},
                plan=analysis,
            )

        matched_chunks = [r.chunk for r in retrieved if r.chunk is not None]
        relevance_by_id = {r.chunk_id: r.score for r in retrieved}
        top_chunks = expand_with_neighbors(matched_chunks, all_chunks, window=neighbor_window)
        return RetrievalResult(
            chunks=top_chunks,
            matched_chunks=matched_chunks,
            intent=plan.depth_bucket,
            is_out_of_scope=False,
            search_query=search_query,
            relevance_by_id=relevance_by_id,
            plan=analysis,
        )

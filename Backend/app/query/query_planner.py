"""QueryPlanner (spec item 6). Decides *how* to search — which of the
existing pipeline's tunable parameters to use — not a new search
algorithm. `HybridSearchService`'s RRF fusion and `RerankerService`'s
weighting stay exactly as Phase 3/4 built them; what the planner
controls is: candidate pool width, how many chunks make it to context,
how much neighbor context to pull in, and the metadata filter to search
within. That's a deliberately narrow scope — changing per-query blend
weights would risk destabilizing the tuned Phase 4 reranking behavior,
so this planner sticks to parameters that are safe to vary per question.
"""

from dataclasses import dataclass

from ..retrieval.models import RetrievalFilters
from .models import Entities, Intent, SearchStrategy

# Intents that benefit from deeper, more explanatory context — mirrors
# the existing binary bucket `retrieval/query_understanding.classify_intent`
# already used for depth (k=8 vs k=4, neighbor_window=1 vs 0). Kept as
# the same two buckets so Retriever's existing depth logic needs no
# changes, just a richer intent feeding into the same decision.
_DEEP_CONTEXT_INTENTS = {
    Intent.EXPLANATION,
    Intent.SUMMARY,
    Intent.COMPARISON,
    Intent.STUDY_NOTES,
    Intent.EXAM_PREPARATION,
    Intent.TIMELINE,
    Intent.CODE_EXPLANATION,
}

_STRATEGY_BY_INTENT = {
    Intent.DEFINITION: SearchStrategy.SEMANTIC_PRIORITY,
    Intent.EXPLANATION: SearchStrategy.SEMANTIC_PRIORITY,
    Intent.FORMULA_EXTRACTION: SearchStrategy.KEYWORD_PRIORITY,
    Intent.CITATION_REQUEST: SearchStrategy.KEYWORD_PRIORITY,
    Intent.CODE_EXPLANATION: SearchStrategy.KEYWORD_PRIORITY,
    Intent.PAGE_REQUEST: SearchStrategy.FILTER_ONLY,
    Intent.COMPARISON: SearchStrategy.MULTI_TARGET,
}


@dataclass
class SearchPlan:
    strategy: SearchStrategy
    filters: RetrievalFilters
    depth_bucket: str  # 'explain' | 'specific' — see retriever.py's existing k/neighbor_window logic
    candidate_count_multiplier: float  # applied to Settings.rerank_candidate_count


class QueryPlanner:
    def plan(self, intent: Intent, entities: Entities) -> SearchPlan:
        strategy = _STRATEGY_BY_INTENT.get(intent, SearchStrategy.HYBRID_BALANCED)

        filters = RetrievalFilters(
            chapter=entities.chapter_hint,
            section=entities.section_hint,
            page=entities.page_references[0] if len(entities.page_references) == 1 else None,
        )

        depth_bucket = "explain" if intent in _DEEP_CONTEXT_INTENTS else "specific"

        # FILTER_ONLY: we already know which page — no need to cast a
        # wide semantic/keyword net across the whole document.
        # MULTI_TARGET: a comparison needs enough headroom for both
        # sides to have a chance at making the cut before reranking.
        if strategy == SearchStrategy.FILTER_ONLY:
            multiplier = 0.5
        elif strategy == SearchStrategy.MULTI_TARGET:
            multiplier = 1.5
        else:
            multiplier = 1.0

        return SearchPlan(
            strategy=strategy, filters=filters, depth_bucket=depth_bucket, candidate_count_multiplier=multiplier
        )

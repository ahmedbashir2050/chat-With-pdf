"""QueryUnderstandingService (spec item 1) — the single entry point for
turning a raw question into a full `QueryAnalysis`. Composes:

- `parsing.language.detect_language` (already used for document chunks
  since Phase 2 — the same Arabic/English/mixed heuristic applies
  equally well to a short question).
- `intent_classifier.LocalIntentClassifier` (or an injected LLM-based
  one).
- `entity_extractor.extract_entities`.
- `query_rewriter.rewrite_query` (wraps the existing LLM rewrite).
- `context.answer_style.classify_answer_style` (already built in Phase 5
  — reused, not reimplemented).
- `query_planner.QueryPlanner`.

Caching (spec item 13): repeated identical (chat_id, question,
history-length) analyses within a session are common — a user editing
and resending, or a client retry — and the expensive part (the LLM
rewrite call) has no reason to run twice for the same input. Keyed on
history length rather than history content: cheap to compute, and
history only grows monotonically within a chat, so a length match is a
reliable proxy for "the same conversation state" without hashing the
full transcript on every call.
"""

from ..context.answer_style import classify_answer_style
from ..domain.interfaces import LLMService
from ..parsing.language import detect_language
from ..retrieval.query_processing import analyze_query as _base_analyze_query
from .entity_extractor import extract_entities
from .intent_classifier import BaseIntentClassifier, LocalIntentClassifier
from .models import QueryAnalysis
from .query_planner import QueryPlanner, SearchPlan
from .query_rewriter import rewrite_query

_CACHE_MAX_SIZE = 256


def _keywords_for(question: str) -> list[str]:
    return _base_analyze_query(question, intent="specific").keywords


class QueryUnderstandingService:
    def __init__(self, llm_service: LLMService, intent_classifier: BaseIntentClassifier | None = None):
        self._llm = llm_service
        self._intent_classifier = intent_classifier or LocalIntentClassifier()
        self._planner = QueryPlanner()
        self._cache: dict[tuple[int, str, int], tuple[QueryAnalysis, SearchPlan]] = {}

    def understand(self, chat_id: int, question: str, history: list[dict]) -> tuple[QueryAnalysis, SearchPlan]:
        cache_key = (chat_id, question, len(history))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        language = detect_language(question)
        intent, complexity = self._intent_classifier.classify(question)
        entities = extract_entities(question)
        rewritten_query = rewrite_query(question, history, self._llm)
        answer_style = classify_answer_style(question)
        plan = self._planner.plan(intent, entities)

        analysis = QueryAnalysis(
            original_query=question,
            rewritten_query=rewritten_query,
            intent=intent,
            language=language,
            entities=entities,
            keywords=_keywords_for(question),
            filters=plan.filters,
            search_strategy=plan.strategy,
            answer_style=answer_style,
            complexity=complexity,
            numbers=entities.numbers,
            page_references=entities.page_references,
            chapter_hint=entities.chapter_hint,
            section_hint=entities.section_hint,
        )

        result = (analysis, plan)
        if len(self._cache) >= _CACHE_MAX_SIZE:
            self._cache.pop(next(iter(self._cache)))  # evict oldest (insertion-ordered dict)
        self._cache[cache_key] = result
        return result

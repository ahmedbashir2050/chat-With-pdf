"""Models for the Phase 6 query understanding layer.

`QueryAnalysis` here is deliberately field-compatible with
`retrieval.models.QueryAnalysis` — it carries the exact same
`keywords`/`numbers`/`page_references`/`chapter_hint`/`section_hint`
attribute names, because those are the only attributes
`HybridSearchService.search()` and `LocalReranker.score()` read off an
`analysis` object. That compatibility means this richer object can be
passed anywhere the old one was, with zero changes to retrieval or
reranking code — "integrate with", not "rewrite", per the brief.
"""

from dataclasses import dataclass, field
from enum import Enum

from ..retrieval.models import RetrievalFilters


class Intent(str, Enum):
    EXPLANATION = "explanation"
    SUMMARY = "summary"
    DEFINITION = "definition"
    COMPARISON = "comparison"
    LIST = "list"
    TIMELINE = "timeline"
    TRANSLATION = "translation"
    QUESTION_ANSWERING = "question_answering"
    FINDING_INFORMATION = "finding_information"
    CITATION_REQUEST = "citation_request"
    PAGE_REQUEST = "page_request"
    FORMULA_EXTRACTION = "formula_extraction"
    CODE_EXPLANATION = "code_explanation"
    EXAM_PREPARATION = "exam_preparation"
    STUDY_NOTES = "study_notes"


class Complexity(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SearchStrategy(str, Enum):
    SEMANTIC_PRIORITY = "semantic_priority"  # definitions/explanations — meaning matters more than exact wording
    KEYWORD_PRIORITY = "keyword_priority"  # exact numbers/formulas/citations — wording matters more than meaning
    FILTER_ONLY = "filter_only"  # "what's on page 12" — the filter IS the answer, ranking barely matters
    MULTI_TARGET = "multi_target"  # comparisons — two things need to be found, not one blended query
    HYBRID_BALANCED = "hybrid_balanced"  # default — trust the existing RRF fusion as-is


@dataclass
class Entities:
    """Extracted entities (spec item 3). `people` and `organizations` are
    deliberately NOT attempted here — reliable extraction needs a real
    NER model; a naive capitalized-word heuristic produces too many false
    positives in English and doesn't work at all for Arabic (no
    capitalization), so promising that field without a model behind it
    would be worse than omitting it. The entities extractable reliably
    with rules — numbers, dates, page/chapter/section references,
    technology/formula terms — are the ones actually implemented."""

    numbers: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    page_references: list[int] = field(default_factory=list)
    chapter_hint: str | None = None
    section_hint: str | None = None


@dataclass
class QueryAnalysis:
    original_query: str
    rewritten_query: str
    intent: Intent
    language: str | None  # 'ar' | 'en' | 'mixed' | None
    entities: Entities
    keywords: list[str]
    filters: RetrievalFilters
    search_strategy: SearchStrategy
    answer_style: str  # see context/answer_style.py's style names
    complexity: Complexity

    # --- retrieval-layer compatibility fields (see module docstring) ---
    numbers: list[str] = field(default_factory=list)
    page_references: list[int] = field(default_factory=list)
    chapter_hint: str | None = None
    section_hint: str | None = None

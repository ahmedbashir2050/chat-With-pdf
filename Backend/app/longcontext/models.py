"""Models for the Phase 7 long-context retrieval layer."""

from dataclasses import dataclass, field
from enum import Enum


class LongContextQueryType(str, Enum):
    NORMAL_QUERY = "normal_query"  # ordinary question — falls through to Phase 3-6's top-k RAG pipeline, unchanged
    PAGE_RANGE = "page_range"
    SECTION_QUERY = "section_query"
    CHAPTER_QUERY = "chapter_query"
    MULTI_CHAPTER_QUERY = "multi_chapter_query"
    DOCUMENT_QUERY = "document_query"


@dataclass
class LongContextPlan:
    query_type: LongContextQueryType
    chapters: list[str] = field(default_factory=list)  # raw chapter references, e.g. ["3"], or ["2", "5"] for a comparison
    page_range: tuple[int, int] | None = None
    section_hint: str | None = None
    explanation_mode: str = "simple"  # see context/answer_style.py's style names, plus 'academic'/'teaching'
    response_length: str = "auto"

    @property
    def is_long_context(self) -> bool:
        return self.query_type != LongContextQueryType.NORMAL_QUERY

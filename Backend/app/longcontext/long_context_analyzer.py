"""LongContextAnalyzer (spec item 1). Classifies a question into one of
six scopes. The page/chapter detection regexes here are the canonical
home for what used to live only inside `qa_service.py`'s
SUMMARY_PATTERN-gated branch (moved, not duplicated) — generalized so
"explain chapter 3" and "give study notes for chapter 4" are recognized
as chapter-scoped requests exactly like "summarize chapter 3" always
was, instead of falling through to ordinary top-k RAG.
"""

import re

from ..context.answer_style import classify_answer_style
from .models import LongContextPlan, LongContextQueryType

PAGE_RANGE_PATTERN = re.compile(
    r"(?:pages?|صفحات|الصفحات)\s*(\d+)\s*(?:-|to|through|–|الى|إلى)\s*(\d+)", re.IGNORECASE
)
SINGLE_PAGE_PATTERN = re.compile(r"\b(?:page|صفحة|الصفحة)\s*(\d+)\b", re.IGNORECASE)
CHAPTER_PATTERN = re.compile(r"\b(?:ch(?:apter)?\.?|الفصل|فصل)\s*(\d+)\b", re.IGNORECASE)

# Arabic chapters are just as often referred to by a spelled-out ordinal
# ("الفصل الثاني" = "chapter two") as by a digit ("الفصل 2").
ARABIC_CHAPTER_ORDINALS = {
    "الأول": 1, "الاول": 1,
    "الثاني": 2,
    "الثالث": 3,
    "الرابع": 4,
    "الخامس": 5,
    "السادس": 6,
    "السابع": 7,
    "الثامن": 8,
    "التاسع": 9,
    "العاشر": 10,
}
_ORDINAL_ALTERNATION = "|".join(sorted(ARABIC_CHAPTER_ORDINALS, key=len, reverse=True))
CHAPTER_ORDINAL_PATTERN = re.compile(rf"(?:الفصل|فصل)\s+({_ORDINAL_ALTERNATION})")

# "compare chapter 2 and chapter 5", "chapters 2 and 5", "chapter 2 vs chapter 6"
MULTI_CHAPTER_PATTERN = re.compile(
    r"chapters?\s*(\d+)\s*(?:and|vs\.?|versus|,)\s*(?:chapter\s*)?(\d+)"
    r"|(?:الفصل|فصل)\s*(\d+)\s*(?:و|مقابل)\s*(?:الفصل|فصل)?\s*(\d+)",
    re.IGNORECASE,
)

DOCUMENT_QUERY_PATTERN = re.compile(
    r"\b(the (whole|entire) document|this (book|document)|the (whole|entire) book|"
    r"summarize (it|this) all|كل المستند|كل الكتاب|المستند بالكامل|الكتاب بالكامل|هذا الكتاب)\b",
    re.IGNORECASE,
)

# A quoted phrase, or "section on/about X", signals a section-scoped
# request rather than a chapter/page one — reused from
# retrieval/query_processing.py's same narrow pattern (only explicit
# phrasing counts, to avoid every question about *some* topic being
# treated as a section request).
_QUOTED_SECTION_RE = re.compile(
    r'(?:section|قسم|الجزء)\s+(?:on|about|called|named|عن|بعنوان)?\s*[:\-]?\s*["\u201c]([^"\u201d]{2,80})["\u201d]',
    re.IGNORECASE,
)
_SECTION_HINT_RE = re.compile(
    r"(?:section|قسم|الجزء)\s+(?:on|about|called|named|عن|بعنوان)?\s*[:\-]?\s*([A-Za-z\u0600-\u06FF][\w \u0600-\u06FF]{1,60})",
    re.IGNORECASE,
)


def _extract_section_hint(question: str) -> str | None:
    quoted = _QUOTED_SECTION_RE.search(question)
    if quoted:
        return quoted.group(1).strip()
    plain = _SECTION_HINT_RE.search(question)
    if plain:
        return plain.group(1).strip()
    return None

# Broad trigger words that suggest *some* long-context treatment is
# wanted even without an explicit page/chapter number — e.g. "explain
# this chapter", "summarize this section" (referring to context rather
# than naming a number).
_LONG_SCOPE_HINT_RE = re.compile(
    r"\b(this chapter|the chapter|this section|the section|study notes for|"
    r"exam (prep|questions) for|هذا الفصل|الفصل هذا|هذا القسم)\b",
    re.IGNORECASE,
)


def _extract_chapter_number(text: str) -> int | None:
    digit_match = CHAPTER_PATTERN.search(text)
    if digit_match:
        return int(digit_match.group(1))
    ordinal_match = CHAPTER_ORDINAL_PATTERN.search(text)
    if ordinal_match:
        return ARABIC_CHAPTER_ORDINALS.get(ordinal_match.group(1))
    return None


def chapter_heading_regex(n: int) -> re.Pattern:
    """Fallback heading-text scanner — used by ChapterRetriever only for
    chunks that have no `.chapter` metadata (pre-Phase-2 fixed-size
    chunker output); the primary path matches `chunk.chapter` directly."""
    alternatives = [rf"chapter\s*0*{n}\b", rf"(?:الفصل|فصل)\s*0*{n}\b"]
    word = next((w for w, num in ARABIC_CHAPTER_ORDINALS.items() if num == n), None)
    if word:
        alternatives.append(rf"(?:الفصل|فصل)\s+{re.escape(word)}\b")
    return re.compile("|".join(alternatives), re.IGNORECASE)


class LongContextAnalyzer:
    def analyze(self, question: str) -> LongContextPlan:
        explanation_mode = classify_answer_style(question)
        response_length = "long" if explanation_mode in ("detailed", "academic", "teaching", "study_notes") else "auto"

        multi_match = MULTI_CHAPTER_PATTERN.search(question)
        if multi_match:
            groups = [g for g in multi_match.groups() if g]
            return LongContextPlan(
                query_type=LongContextQueryType.MULTI_CHAPTER_QUERY,
                chapters=groups[:2],
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        range_match = PAGE_RANGE_PATTERN.search(question)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            return LongContextPlan(
                query_type=LongContextQueryType.PAGE_RANGE,
                page_range=(min(start, end), max(start, end)),
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        chapter_n = _extract_chapter_number(question)
        if chapter_n is not None:
            return LongContextPlan(
                query_type=LongContextQueryType.CHAPTER_QUERY,
                chapters=[str(chapter_n)],
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        if DOCUMENT_QUERY_PATTERN.search(question):
            return LongContextPlan(
                query_type=LongContextQueryType.DOCUMENT_QUERY,
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        section_match_text = _extract_section_hint(question)
        if section_match_text:
            return LongContextPlan(
                query_type=LongContextQueryType.SECTION_QUERY,
                section_hint=section_match_text,
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        single_page = SINGLE_PAGE_PATTERN.search(question)
        if single_page:
            page = int(single_page.group(1))
            return LongContextPlan(
                query_type=LongContextQueryType.PAGE_RANGE,
                page_range=(page, page),
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        if _LONG_SCOPE_HINT_RE.search(question):
            # A scope was implied ("this chapter") but no number was
            # given — without conversation context we can't resolve
            # *which* chapter, so this still counts as a long-context
            # request; the caller falls back to DOCUMENT_QUERY-style
            # handling (whatever chunks are already in the active
            # retrieval/conversation context) rather than guessing a
            # chapter number.
            return LongContextPlan(
                query_type=LongContextQueryType.DOCUMENT_QUERY,
                explanation_mode=explanation_mode,
                response_length=response_length,
            )

        return LongContextPlan(
            query_type=LongContextQueryType.NORMAL_QUERY,
            explanation_mode=explanation_mode,
            response_length=response_length,
        )

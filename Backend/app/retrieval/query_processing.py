"""Query Understanding — the first stage of the hybrid pipeline. Turns
the raw question into structured signals (`QueryAnalysis`) that later
stages use: `RetrievalFilters` are derived from the chapter/section/page
hints here, and the reranker boosts chunks whose text contains the
extracted keywords/numbers verbatim.

Kept separate from `query_understanding.py` (intent classification,
query rewriting, response-length inference) deliberately — that module
is about *how to answer*, this one is about *what to search for*. They
compose (this module calls `classify_intent` from that one) rather than
merging, so each stays focused on one job.
"""

import re

from .models import QueryAnalysis

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_PAGE_RE = re.compile(r"(?:page|صفحة|ص)\s*\.?\s*(\d+)", re.IGNORECASE)

_CHAPTER_RE = re.compile(
    r"(chapter\s+\d+|chapter\s+[ivxlcdm]+|الفصل\s+\S+)", re.IGNORECASE
)

# A quoted phrase, or "section on/about X" / "قسم عن X", is treated as a
# section hint. Deliberately narrow — an unquoted bare noun phrase is too
# likely to be a false positive (nearly every question mentions *some*
# topic), so only these explicit patterns set section_hint.
_QUOTED_RE = re.compile(r'["\u201c]([^"\u201d]{2,80})["\u201d]')
_SECTION_HINT_RE = re.compile(
    r"(?:section|قسم|الجزء)\s+(?:on|about|called|named|عن|بعنوان)?\s*[:\-]?\s*([A-Za-z\u0600-\u06FF][\w \u0600-\u06FF]{1,60})",
    re.IGNORECASE,
)

# Minimal stopword lists — just enough to keep `keywords` from being
# dominated by function words; not meant to be linguistically complete.
_EN_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "in", "on",
    "at", "to", "for", "and", "or", "what", "which", "who", "how", "why", "does",
    "do", "did", "this", "that", "these", "those", "it", "its", "with", "from",
    "about", "explain", "page", "chapter", "section",
}
_AR_STOPWORDS = {
    "من", "في", "على", "إلى", "الى", "عن", "ما", "هل", "هذا", "هذه", "ذلك",
    "كيف", "لماذا", "ماذا", "و", "أو", "او", "صفحة", "الفصل", "قسم",
}
_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def _extract_keywords(question: str) -> list[str]:
    tokens = _TOKEN_RE.findall(question.lower())
    keywords = []
    for t in tokens:
        if t in _EN_STOPWORDS or t in _AR_STOPWORDS:
            continue
        if len(t) < 2:
            continue
        keywords.append(t)
    return keywords


def _extract_section_hint(question: str) -> str | None:
    quoted = _QUOTED_RE.search(question)
    if quoted:
        return quoted.group(1).strip()
    hinted = _SECTION_HINT_RE.search(question)
    if hinted:
        return hinted.group(1).strip()
    return None


def analyze_query(question: str, intent: str) -> QueryAnalysis:
    """`intent` is passed in rather than recomputed here — the caller
    (Retriever) already calls `classify_intent` for response-length
    purposes, and there's no reason to derive it twice from the same
    text."""
    numbers = _NUMBER_RE.findall(question)
    page_references = [int(m) for m in _PAGE_RE.findall(question)]

    chapter_match = _CHAPTER_RE.search(question)
    chapter_hint = chapter_match.group(1).strip() if chapter_match else None

    section_hint = _extract_section_hint(question)

    return QueryAnalysis(
        raw_question=question,
        intent=intent,
        keywords=_extract_keywords(question),
        numbers=numbers,
        page_references=page_references,
        chapter_hint=chapter_hint,
        section_hint=section_hint,
    )

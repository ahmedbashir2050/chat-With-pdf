"""Metadata filtering (spec item 7). Applied *before* semantic/keyword
search runs, so "from chapter 3 only" actually narrows the candidate
pool rather than just being a post-hoc relevance signal.

Deliberately permissive matching (substring, case-insensitive) rather
than exact equality — chapter/section text comes from the hierarchy
detector's heuristics (Phase 2), not a controlled vocabulary, so a user
saying "chapter 3" needs to match a chunk whose `.chapter` field reads
"Chapter 3: Neural Networks" or "الفصل الثالث: الشبكات العصبية".
"""

from ..domain.entities import DocumentChunk
from .models import RetrievalFilters


def _contains(haystack: str | None, needle: str | None) -> bool:
    if not needle:
        return True
    if not haystack:
        return False
    return needle.strip().lower() in haystack.strip().lower()


def apply_metadata_filters(chunks: list[DocumentChunk], filters: RetrievalFilters | None) -> list[DocumentChunk]:
    """Returns the subset of `chunks` matching every non-None field on
    `filters`. Returns `chunks` unchanged if `filters` is None or empty
    — callers should treat an empty *result* (a filter that matched
    nothing) as a signal to fall back to the unfiltered pool rather than
    silently reporting no results; see hybrid_search.py."""
    if filters is None or filters.is_empty():
        return chunks

    result = []
    for c in chunks:
        if filters.document_id is not None and c.document_id != filters.document_id:
            continue
        if not _contains(c.chapter, filters.chapter):
            continue
        if not _contains(c.section, filters.section):
            continue
        if filters.page is not None and c.page != filters.page:
            continue
        result.append(c)
    return result

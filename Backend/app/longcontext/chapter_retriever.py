"""ChapterRetriever and SectionRetriever (spec item 2). This is where
Phase 2's `chunk.chapter`/`.section` metadata — populated by document
intelligence since Phase 2 but, until now, only ever regex-scanned for
against raw chunk *text* (the old `qa_service._answer_summary` approach)
— finally gets used directly. Matching against the structured field is
strictly more reliable than searching for a heading string inside body
text: a heading regex can match a *mention* of "Chapter 3" inside prose
that isn't actually chapter 3's own heading, and won't match at all if
the heading was rendered as an image or split across two text blocks.

The heading-regex fallback (`long_context_analyzer.chapter_heading_regex`)
is kept for exactly one case: chunks with no `.chapter` metadata at all —
i.e. documents parsed before Phase 2's hierarchy detection existed, or
any future parser that doesn't populate it. New documents don't need it.
"""

from ..domain.entities import DocumentChunk
from .long_context_analyzer import chapter_heading_regex


def _normalize_chapter_number(chapter_text: str | None) -> int | None:
    """Pulls a leading chapter number out of a chunk's `.chapter` field
    (e.g. "Chapter 3: Neural Networks" -> 3, "الفصل 3" -> 3) so it can be
    compared against the number the user asked for, regardless of
    exactly how the hierarchy detector phrased the heading."""
    if not chapter_text:
        return None
    import re

    match = re.search(r"\d+", chapter_text)
    return int(match.group()) if match else None


def _sort_key(c: DocumentChunk) -> tuple:
    """Page then paragraph index, per spec item 2's "preserve original
    reading order". `chapter`/`section` are deliberately NOT included as
    sort keys here — sorting by section *text* would order sections
    alphabetically ("Backpropagation" before "Introduction"), which is
    not reading order. Within one already chapter-filtered chunk list,
    page+paragraph order alone correctly reconstructs section-by-section
    reading order, since a section's content is naturally contiguous by
    page in a linearly-authored document. (Multi-chapter retrieval keeps
    each chapter's chunks in a separate list rather than concatenating
    them — see `retrieve_multi` — so there's no cross-chapter ordering
    question to resolve here either.)"""
    return (c.page, c.paragraph_index if c.paragraph_index is not None else 0)


class ChapterRetriever:
    def retrieve_chapter(self, chapter_ref: str, all_chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        """`chapter_ref` is a plain number as a string (e.g. "3") — see
        LongContextAnalyzer, which is what produces these."""
        try:
            target_number = int(chapter_ref)
        except ValueError:
            target_number = None

        matched = [c for c in all_chunks if c.chapter and _normalize_chapter_number(c.chapter) == target_number]

        if not matched and target_number is not None:
            # Fallback for chunks with no chapter metadata at all.
            heading_re = chapter_heading_regex(target_number)
            start_idx = next((i for i, c in enumerate(all_chunks) if heading_re.search(c.text)), None)
            if start_idx is not None:
                next_heading_re = chapter_heading_regex(target_number + 1)
                end_idx = next(
                    (i for i, c in enumerate(all_chunks) if i > start_idx and next_heading_re.search(c.text)),
                    len(all_chunks),
                )
                matched = all_chunks[start_idx:end_idx]

        return sorted(matched, key=_sort_key)

    def retrieve_multi(self, chapter_refs: list[str], all_chunks: list[DocumentChunk]) -> dict[str, list[DocumentChunk]]:
        """For multi-chapter comparison (spec item 9) — each chapter's
        chunks retrieved and ordered independently, kept separate rather
        than concatenated, since a comparison needs to reason about each
        side distinctly before contrasting them."""
        return {ref: self.retrieve_chapter(ref, all_chunks) for ref in chapter_refs}


class SectionRetriever:
    def retrieve_section(self, section_hint: str, all_chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        hint_lower = section_hint.strip().lower()
        matched = [
            c
            for c in all_chunks
            if (c.section and hint_lower in c.section.lower())
            or (c.subsection and hint_lower in c.subsection.lower())
            or (c.heading and hint_lower in c.heading.lower())
        ]
        return sorted(matched, key=_sort_key)

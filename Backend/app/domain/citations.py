"""Citation model — the user-visible "where did this answer come from"
data attached to every RAG/summary response. Framework-agnostic (no
FastAPI/Pydantic here) for the same reason domain/entities.py is: this is
built once, in the application layer, and adapted to an API schema
(schemas.CitationOut) only at the router boundary.

SINGLE AUTHORITATIVE PAGE FIELD: `physical_page` — the 1-based physical
PDF page index (`physical_page = i + 1` at parse time; see
parsing/document_parser_v2.py). This is the ONLY page identity a
citation ever carries or displays. There used to be a `page_label`/
`display_page` concept here that preferred the document's own *printed*
page label (roman numerals, abjad letters, a printed number that
restarts or differs from the physical index) when the parser detected
one, falling back to the physical page otherwise. That preference rule
has been deliberately removed: a citation must always point at the
physical page a PDF viewer would land on, never at a label that could
be ambiguous, duplicated across a document (front-matter "i, ii, iii"
restarting into body "1, 2, 3"), or simply wrong for the LLM to copy
verbatim. `chunk.page_label` (the parser's detection of a printed label)
still exists as general document metadata for *other*, non-citation
features — it just has zero influence on anything in this module.
"""

from dataclasses import dataclass

from .entities import DocumentChunk


def physical_page_citation_value(chunk: DocumentChunk) -> str:
    """The page value used wherever this chunk is cited — always
    `str(chunk.physical_page)`, the 1-based physical PDF page index.
    Returns the bare value (e.g. `"12"`), not a bracketed `"[p. 12]"`
    string — callers that need the full marker wrap it themselves (e.g.
    `f"[p. {physical_page_citation_value(chunk)}]"`), since some callers
    instead need the bare value for set-membership comparisons (citation
    validation, claim verification) rather than display text.

    Kept as a function (rather than inlining `str(chunk.physical_page)`
    at every call site) so every caller — the LLM prompt, citation
    validation, claim verification, the structured `Citation` object —
    keeps reading from exactly one place, and so a future change can't
    silently reintroduce a second, competing notion of "the" citation
    page without being obvious in a diff of this one function.

    Previously named `citation_display_page` — renamed because
    "display page" implied a separate, possibly-different-from-physical
    "display" concept, which this project has deliberately removed
    entirely (see this module's docstring)."""
    return str(chunk.physical_page)


@dataclass
class Citation:
    document_id: str | None
    physical_page: int
    chapter: str | None
    section: str | None
    heading: str | None
    bbox: tuple[float, float, float, float] | None


def build_citation(chunk: DocumentChunk) -> Citation:
    return Citation(
        document_id=chunk.document_id,
        physical_page=chunk.physical_page,
        chapter=chunk.chapter,
        section=chunk.section,
        heading=chunk.heading,
        bbox=chunk.bbox,
    )


def build_citations(chunks: list[DocumentChunk], limit: int | None = None) -> list[Citation]:
    """Builds one citation per *distinct* source location, in the order
    chunks were given. "Distinct" is keyed on (physical_page, section,
    heading) rather than chunk id, so two chunks that both land on the
    same page/section — e.g. a matched chunk and a neighbor pulled in
    for context — collapse into a single citation instead of showing the
    same page twice.
    """
    seen: set[tuple[int, str | None, str | None]] = set()
    citations: list[Citation] = []

    for chunk in chunks:
        key = (chunk.physical_page, chunk.section, chunk.heading)
        if key in seen:
            continue
        seen.add(key)
        citations.append(build_citation(chunk))
        if limit is not None and len(citations) >= limit:
            break

    return citations

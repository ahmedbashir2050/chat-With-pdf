"""Context ordering (spec item 3). The spec lists four rules — same
section together, same chapter together, logical page order, highest
relevance first — which read as complementary rather than a strict
priority chain (grouping by section AND ordering by page within a group
both matter at once). The interpretation implemented here: chunks are
grouped by (chapter, section); groups are ordered by their best
relevance score (highest first — this is what surfaces the most
relevant material at the top of the prompt); *within* a group, chunks
are ordered by page (this is what fixes the spec's own bad-example:
page 50, page 10, page 51 -> page 10, page 11, page 12).

Chunks with no chapter/section (hierarchy detection found nothing, or
this came from the pre-Phase-2 fixed-size chunker) form their own
group keyed on (None, None), ordered by page like any other group.
"""

from dataclasses import dataclass

from ..domain.entities import DocumentChunk


@dataclass
class ScoredChunk:
    chunk: DocumentChunk
    relevance: float


def order_context(scored_chunks: list[ScoredChunk]) -> list[DocumentChunk]:
    """`scored_chunks` pairs each chunk with the relevance score it was
    retrieved/reranked with — needed to rank *groups* by relevance even
    though chunks are reordered by page *within* a group."""
    groups: dict[tuple[str | None, str | None], list[ScoredChunk]] = {}
    for sc in scored_chunks:
        key = (sc.chunk.chapter, sc.chunk.section)
        groups.setdefault(key, []).append(sc)

    def group_relevance(group: list[ScoredChunk]) -> float:
        return max(sc.relevance for sc in group)

    ordered_groups = sorted(groups.values(), key=group_relevance, reverse=True)

    result: list[DocumentChunk] = []
    for group in ordered_groups:
        group.sort(key=lambda sc: sc.chunk.page)
        result.extend(sc.chunk for sc in group)
    return result


def order_chunks_with_scores(chunks: list[DocumentChunk], relevance_by_id: dict) -> list[DocumentChunk]:
    """Convenience wrapper for callers that already have a plain chunk
    list and a separate {chunk_id: score} map (e.g. from RetrievedChunk
    results) rather than paired (chunk, score) tuples."""
    scored = [ScoredChunk(chunk=c, relevance=relevance_by_id.get(c.id, 0.0)) for c in chunks]
    return order_context(scored)

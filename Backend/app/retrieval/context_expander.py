"""Context expansion — the last stage of the hybrid pipeline before a
final answer is generated. Unchanged in behavior from Phase 1/2 (moved
here, not rewritten, per the spec's dedicated-file-per-responsibility
layout): pulls in the chunk(s) immediately before/after each matched
result, in document order, so the model isn't reasoning over an isolated
~400-token fragment cut off mid-thought.

Citations are unaffected by this stage — `Retriever` builds citations
from the pre-expansion `matched_chunks` list (see retriever.py and
domain/citations.py), never from the expanded list this function
returns, so a neighbor pulled in purely for surrounding context is never
mistakenly cited as a source in its own right.
"""

from ..domain.entities import DocumentChunk


def expand_with_neighbors(
    selected: list[DocumentChunk], all_chunks_ordered: list[DocumentChunk], window: int = 1
) -> list[DocumentChunk]:
    """Adds the chunk(s) immediately before/after each selected match (by
    document order), so the model sees a bit of surrounding context
    instead of an isolated fragment. Chunk boundaries fall mid-thought
    fairly often; this noticeably reduces answers that feel cut off or
    miss context available one sentence away.

    Deduplicated and returned in document order (not match-rank order)
    — the model reads more coherently with pages/paragraphs in their
    natural sequence than with the highest-ranked match first.
    """
    if window <= 0:
        return selected

    index_of = {c.id: i for i, c in enumerate(all_chunks_ordered)}
    expanded_indices: set[int] = set()
    for c in selected:
        i = index_of.get(c.id)
        if i is None:
            continue
        for j in range(i - window, i + window + 1):
            if 0 <= j < len(all_chunks_ordered):
                expanded_indices.add(j)

    return [all_chunks_ordered[i] for i in sorted(expanded_indices)]

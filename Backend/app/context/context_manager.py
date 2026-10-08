"""ContextManagerService — orchestrates the context preparation pipeline
(spec item 1): dedup -> merge adjacent related chunks -> order -> clean
-> compress to a token budget. Sits between retrieval (Phase 3/4, whose
output — `list[RetrievedChunk]` from HybridSearchService, already
neighbor-expanded into `list[DocumentChunk]` by Retriever — is
unchanged) and prompt building (`application/prompts.py`, also
unchanged): this layer's whole job is producing the best possible
`list[DocumentChunk]` for that existing prompt code to render, not
replacing it.
"""

from dataclasses import replace

from ..domain.entities import DocumentChunk
from ..retrieval.models import QueryAnalysis
from .context_compressor import clean_text, compress_chunk
from .context_ranker import ScoredChunk, order_context
from .models import PreparedContext
from .token_utils import estimate_tokens, estimate_total_tokens

# Once a chunk is compressed below this many tokens, further trimming
# stops being worth the readability cost — better to drop a whole
# low-relevance chunk than reduce every chunk to a fragment.
MIN_CHUNK_TOKENS_AFTER_COMPRESSION = 40


def _dedupe(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Removes exact-duplicate chunk ids (the same chunk pulled in twice
    — e.g. as both a directly matched result and a neighbor of another
    match) and near-duplicate text (one chunk's text fully contained in
    another's — can happen when a small chunk is a strict subset of a
    merged neighbor). Keeps the first occurrence, preserving whatever
    order the caller passed in."""
    seen_ids: set = set()
    kept: list[DocumentChunk] = []
    kept_texts: list[str] = []

    for c in chunks:
        if c.id is not None and c.id in seen_ids:
            continue
        normalized = " ".join(c.text.split()).lower()
        if any(normalized and (normalized in kept_norm or kept_norm in normalized) for kept_norm in kept_texts):
            continue
        seen_ids.add(c.id)
        kept.append(c)
        kept_texts.append(normalized)

    return kept


def _merge_adjacent(chunks: list[DocumentChunk]) -> tuple[list[DocumentChunk], list]:
    """Merges chunks that are direct document-order neighbors (linked via
    previous_chunk_id/next_chunk_id — see semantic_chunker.py) AND share
    the same chapter/section, into a single combined chunk. This is what
    "merge related chunks" means here: two adjacent fragments of the same
    paragraph/section read better — and cost fewer tokens overall than
    two separate headers — combined into one excerpt than sent as two.
    Chunks without a local_id (pre-Phase-2 fixed-size chunker output)
    are left as-is; merging needs the prev/next linkage to know adjacency
    safely rather than guessing from page numbers alone."""
    by_local_id = {c.local_id: c for c in chunks if c.local_id}
    merged_ids: list = []
    used: set = set()
    result: list[DocumentChunk] = []

    for c in chunks:
        if c.local_id in used:
            continue
        if not c.local_id:
            result.append(c)
            continue

        group = [c]
        used.add(c.local_id)
        # Walk forward through next_chunk_id while the neighbor is also
        # in our selected set and shares chapter+section.
        cursor = c
        while (
            cursor.next_chunk_id
            and cursor.next_chunk_id in by_local_id
            and cursor.next_chunk_id not in used
            and by_local_id[cursor.next_chunk_id].chapter == c.chapter
            and by_local_id[cursor.next_chunk_id].section == c.section
        ):
            nxt = by_local_id[cursor.next_chunk_id]
            group.append(nxt)
            used.add(nxt.local_id)
            cursor = nxt

        if len(group) == 1:
            result.append(c)
            continue

        merged_text = "\n\n".join(g.text for g in group)
        merged_ids.extend(g.local_id for g in group)
        result.append(replace(group[0], text=merged_text, word_count=len(merged_text.split())))

    return result, merged_ids


class ContextManagerService:
    def prepare(
        self,
        chunks: list[DocumentChunk],
        relevance_by_id: dict,
        token_budget: int,
        analysis: QueryAnalysis | None = None,
    ) -> PreparedContext:
        """`relevance_by_id` maps chunk.id -> the relevance score it was
        retrieved/reranked with (used only for ordering groups — see
        context_ranker.py). `analysis` (from query_processing.py) drives
        compression's sentence scoring; compression is skipped entirely
        if not provided, since there'd be no query signal to score
        sentences against."""
        if not chunks:
            return PreparedContext(chunks=[], total_tokens=0)

        deduped = _dedupe(chunks)
        merged, merged_ids = _merge_adjacent(deduped)

        cleaned = [replace(c, text=clean_text(c.text)) for c in merged]

        scored = [ScoredChunk(chunk=c, relevance=relevance_by_id.get(c.id, 0.0)) for c in cleaned]
        ordered = order_context(scored)

        final_chunks, dropped_ids, compressed_ids = self._fit_to_budget(ordered, token_budget, analysis)

        return PreparedContext(
            chunks=final_chunks,
            total_tokens=estimate_total_tokens(final_chunks),
            dropped_chunk_ids=dropped_ids,
            compressed_chunk_ids=compressed_ids,
            merged_chunk_ids=merged_ids,
        )

    @staticmethod
    def _fit_to_budget(
        chunks: list[DocumentChunk], token_budget: int, analysis: QueryAnalysis | None
    ) -> tuple[list[DocumentChunk], list, list]:
        total = estimate_total_tokens(chunks)
        if total <= token_budget or not chunks:
            return chunks, [], []

        keywords = analysis.keywords if analysis else []
        numbers = analysis.numbers if analysis else []

        # Pass 1: compress chunks (lowest-relevance / last-in-order
        # first, since `chunks` is already ordered highest-relevance-
        # group-first) down toward a per-chunk floor, stopping as soon as
        # the total fits — most questions don't need every chunk
        # compressed, just the least-relevant ones trimmed.
        working = list(chunks)
        compressed_ids: list = []
        if keywords or numbers:
            for i in range(len(working) - 1, -1, -1):
                if estimate_total_tokens(working) <= token_budget:
                    break
                original = working[i]
                floor = min(MIN_CHUNK_TOKENS_AFTER_COMPRESSION, token_budget)
                target = max(floor, min(estimate_tokens(original.text) // 2, token_budget))
                compressed = compress_chunk(original, target, keywords, numbers)
                if compressed is not original:
                    working[i] = compressed
                    compressed_ids.append(original.id)

        # Pass 2: if still over budget after compression, drop whole
        # chunks from the lowest-relevance end until it fits. Dropping
        # (not further shredding) preserves the chunks that remain as
        # coherent, citable excerpts rather than compressing everything
        # into unreadable fragments.
        dropped_ids: list = []
        while working and estimate_total_tokens(working) > token_budget:
            removed = working.pop()
            dropped_ids.append(removed.id)

        return working, dropped_ids, compressed_ids

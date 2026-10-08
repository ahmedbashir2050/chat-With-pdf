"""Shared models for the context management layer."""

from dataclasses import dataclass, field

from ..domain.entities import DocumentChunk


@dataclass
class PreparedContext:
    """The final, LLM-ready chunk list — deduplicated, merged, ordered,
    and compressed to fit a token budget. `prompts.py` (application
    layer) turns `.chunks` into prompt text exactly as it already did in
    Phase 1-4; nothing about prompt *rendering* changes, only what feeds
    into it.
    """

    chunks: list[DocumentChunk]
    total_tokens: int
    dropped_chunk_ids: list[int | str | None] = field(default_factory=list)
    compressed_chunk_ids: list[int | str | None] = field(default_factory=list)
    merged_chunk_ids: list[int | str | None] = field(default_factory=list)

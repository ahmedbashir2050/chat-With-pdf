"""Token estimation. Deliberately the same word-count heuristic
semantic_chunker.py already uses (`word_count * 1.3`) rather than adding
a tokenizer dependency (tiktoken) — this is a budgeting heuristic, not
something that needs to exactly match the LLM provider's own tokenizer.
Centralized here so context_compressor.py and context_manager.py agree
on one number rather than each estimating slightly differently.
"""

from ..domain.entities import DocumentChunk

TOKENS_PER_WORD = 1.3


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return int(len(text.split()) * TOKENS_PER_WORD)


def estimate_chunk_tokens(chunk: DocumentChunk) -> int:
    return estimate_tokens(chunk.text)


def estimate_total_tokens(chunks: list[DocumentChunk]) -> int:
    return sum(estimate_chunk_tokens(c) for c in chunks)

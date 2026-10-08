"""Context compression (spec items 2 and 4). Two distinct jobs:

1. `clean_text` — always applied, regardless of token budget: collapse
   repeated whitespace, drop consecutive duplicate lines (a common OCR
   artifact — the same line scanned/recognized twice in a row), and drop
   lines that are pure noise (a handful of repeated symbols, no real
   content). This never removes meaning, just junk.

2. `compress_chunk` — extractive sentence-level trimming, applied only
   when the context as a whole exceeds its token budget (see
   context_manager.py). Scores each sentence by keyword/number overlap
   with the query and keeps the highest-scoring ones *in their original
   order* (never reordering within a chunk — that would risk changing
   meaning). Returns a new `DocumentChunk` (via `dataclasses.replace`) —
   every other field, including citation-relevant ones (page, chapter,
   section, heading, bbox, document_id), is untouched, which is
   what "the compressed context must still reference document/page/
   section" means in practice: those live on the chunk object, not in
   the text being trimmed.

No LLM call here deliberately — an LLM-based compressor (summarize each
chunk before including it) was considered but rejected for the default
path: it adds a call (cost + latency) per chunk on every question, for a
problem that only occurs when retrieval legitimately returns more
content than fits. Extractive trimming is instant and free; it's the
right default, with an LLM-based compressor a reasonable future
alternative behind the same function signature if quality demands it.
"""

import re
from dataclasses import replace

from ..domain.entities import DocumentChunk
from .token_utils import estimate_tokens

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_NOISE_LINE_RE = re.compile(r"^[\W_]{1,10}$")  # a line of pure punctuation/symbols, no letters or digits

# Sentence boundaries: Latin .!? and the Arabic equivalents (، is a comma,
# not a sentence end, so it's deliberately excluded; ؟ and ۔ are).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟۔])\s+")

MIN_SENTENCES_KEPT = 1  # never compress a chunk down to nothing


def clean_text(text: str) -> str:
    if not text:
        return text

    lines = text.split("\n")
    cleaned_lines: list[str] = []
    previous_normalized: str | None = None

    for line in lines:
        stripped = _WHITESPACE_RE.sub(" ", line).strip()
        if not stripped:
            cleaned_lines.append("")
            previous_normalized = None
            continue
        if _NOISE_LINE_RE.match(stripped):
            continue  # drop pure-symbol noise lines (common scan/OCR artifact)
        if stripped == previous_normalized:
            continue  # drop an immediate duplicate line (repeated OCR pass)
        cleaned_lines.append(stripped)
        previous_normalized = stripped

    result = "\n".join(cleaned_lines)
    result = _BLANK_LINES_RE.sub("\n\n", result)
    return result.strip()


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _sentence_score(sentence: str, keywords: list[str], numbers: list[str]) -> float:
    lower = sentence.lower()
    score = 0.0
    for kw in keywords:
        if kw in lower:
            score += 1.0
    for n in numbers:
        if n in sentence:
            score += 1.5  # exact numbers (equation/table/figure refs) are strong signal
    return score


def compress_chunk(chunk: DocumentChunk, target_tokens: int, keywords: list[str], numbers: list[str]) -> DocumentChunk:
    """Trims `chunk.text` down to roughly `target_tokens`, keeping the
    highest-scoring sentences in their original order. If the chunk is
    already at or under budget, returns it unchanged (same object, not a
    copy — callers can compare identity to know nothing was compressed)."""
    current_tokens = estimate_tokens(chunk.text)
    if current_tokens <= target_tokens:
        return chunk

    sentences = _split_sentences(chunk.text)
    if len(sentences) <= MIN_SENTENCES_KEPT:
        return chunk  # nothing smaller to extract without destroying the one sentence there is

    scored = [(i, s, _sentence_score(s, keywords, numbers)) for i, s in enumerate(sentences)]
    # Keep sentences by score until the budget is filled, then restore
    # original order — this is what keeps the compressed text readable
    # rather than a scrambled bag of high-scoring fragments.
    by_score = sorted(scored, key=lambda item: item[2], reverse=True)

    kept_indices: set[int] = set()
    kept_tokens = 0
    for i, s, _score in by_score:
        s_tokens = estimate_tokens(s)
        if kept_tokens + s_tokens > target_tokens and len(kept_indices) >= MIN_SENTENCES_KEPT:
            continue
        kept_indices.add(i)
        kept_tokens += s_tokens

    kept_sentences = [sentences[i] for i in sorted(kept_indices)]
    compressed_text = " ".join(kept_sentences)
    return replace(chunk, text=compressed_text, word_count=len(compressed_text.split()))

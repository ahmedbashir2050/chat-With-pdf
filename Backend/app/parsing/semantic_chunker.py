"""Semantic chunking. Replaces the old fixed-size word-count splitter
(which could cut a sentence — or a table row — in half) with chunking
that respects the document's own structure:

- A chunk never splits inside a paragraph or list item.
- Heading blocks start a new chunk (so a chunk doesn't straddle a
  section boundary) unless the current chunk is still very small, in
  which case the heading is folded in with what follows.
- Small paragraphs are merged forward until the target size range is
  reached.
- Each chunk is tagged with the chapter/section/subsection/heading it
  falls under, plus a stable local_id and prev/next links, so retrieval
  can show "this came from Chapter 3 > Background" and expand_with_neighbors
  can hop chunk-to-chunk without needing a DB round-trip.

Token counts are approximated as word_count * 1.3 (roughly right for
English/Arabic mixed text without pulling in a tokenizer dependency —
this is a chunk-sizing heuristic, not something that needs to be exact).
"""

import uuid

from ..domain.entities import DocumentChunk
from .hierarchy import ClassifiedBlock, current_context
from .language import detect_language
from .models import ChunkType, HierarchyLevel

TARGET_MIN_TOKENS = 300
TARGET_MAX_TOKENS = 600
TOKENS_PER_WORD = 1.3

_LEVEL_TO_CHUNK_TYPE = {
    HierarchyLevel.TITLE: ChunkType.TITLE,
    HierarchyLevel.CHAPTER: ChunkType.CHAPTER,
    HierarchyLevel.SECTION: ChunkType.SECTION,
    HierarchyLevel.SUBSECTION: ChunkType.SUBSECTION,
    HierarchyLevel.HEADING: ChunkType.HEADING,
    HierarchyLevel.PARAGRAPH: ChunkType.PARAGRAPH,
    HierarchyLevel.LIST_ITEM: ChunkType.LIST_ITEM,
}

_HEADING_LEVELS = {
    HierarchyLevel.TITLE,
    HierarchyLevel.CHAPTER,
    HierarchyLevel.SECTION,
    HierarchyLevel.SUBSECTION,
    HierarchyLevel.HEADING,
}


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * TOKENS_PER_WORD)


class _ChunkBuilder:
    def __init__(self):
        self.pieces: list[str] = []
        self.page: int | None = None
        self.chunk_type: ChunkType = ChunkType.PARAGRAPH
        self.bbox: tuple[float, float, float, float] | None = None
        self.paragraph_indices: list[int] = []

    def add(self, block_text: str, page: int, level: HierarchyLevel, bbox, paragraph_index: int) -> None:
        mapped = _LEVEL_TO_CHUNK_TYPE.get(level, ChunkType.PARAGRAPH)
        if self.page is None:
            self.page = page
            self.chunk_type = mapped
        elif mapped != self.chunk_type:
            self.chunk_type = ChunkType.MIXED
        self.pieces.append(block_text)
        if self.bbox is None:
            self.bbox = bbox
        else:
            x0, y0, x1, y1 = self.bbox
            nx0, ny0, nx1, ny1 = bbox
            self.bbox = (min(x0, nx0), min(y0, ny0), max(x1, nx1), max(y1, ny1))
        self.paragraph_indices.append(paragraph_index)

    @property
    def token_count(self) -> int:
        return _estimate_tokens(" ".join(self.pieces))

    @property
    def is_empty(self) -> bool:
        return not self.pieces

    def text(self) -> str:
        return "\n\n".join(self.pieces).strip()


def chunk_document(
    classified_blocks: list[ClassifiedBlock],
    chat_id: int,
    document_id: str,
) -> list[DocumentChunk]:
    """`classified_blocks` must already be in whole-document reading
    order (concatenated across pages in page order — two-column pages
    are already reordered by layout_parser). Returns finished
    DocumentChunk objects with hierarchy context, language, word count,
    and prev/next links populated."""
    chunks: list[DocumentChunk] = []
    builder = _ChunkBuilder()
    paragraph_index = 0
    seen_so_far: list[ClassifiedBlock] = []

    def flush(force: bool = False) -> None:
        nonlocal builder
        if builder.is_empty:
            return
        if not force and builder.token_count < TARGET_MIN_TOKENS:
            return  # keep accumulating
        _finalize(builder)
        builder = _ChunkBuilder()

    def _finalize(b: "_ChunkBuilder") -> None:
        text = b.text()
        if not text:
            return
        context = current_context(seen_so_far)
        chunk = DocumentChunk(
            chat_id=chat_id,
            page=b.page or 1,  # physical page — the only page field a chunk/citation ever carries
            page_label=None,  # no longer auto-detected per-chunk (nothing consumes it there — see entities.py)
            text=text,
            document_id=document_id,
            chapter=context["chapter"],
            section=context["section"],
            subsection=context["subsection"],
            heading=context["heading"],
            paragraph_index=b.paragraph_indices[0] if b.paragraph_indices else None,
            bbox=b.bbox,
            language=detect_language(text),
            word_count=len(text.split()),
            chunk_type=b.chunk_type.value,
            local_id=str(uuid.uuid4()),
        )
        chunks.append(chunk)

    for item in classified_blocks:
        seen_so_far.append(item)

        if item.level in _HEADING_LEVELS:
            # A heading always closes out a chunk that's already reached
            # a reasonable size, so the new section starts its own chunk.
            # If the current chunk is still tiny, fold the heading in
            # (e.g. a short intro paragraph immediately followed by the
            # first subsection heading) rather than emitting a
            # near-empty chunk.
            if not builder.is_empty and builder.token_count >= TARGET_MIN_TOKENS // 2:
                flush(force=True)
            builder.add(item.block.text, item.block.page, item.level, item.block.bbox, paragraph_index)
            continue

        builder.add(item.block.text, item.block.page, item.level, item.block.bbox, paragraph_index)
        paragraph_index += 1

        if builder.token_count > TARGET_MAX_TOKENS:
            flush(force=True)
        else:
            flush(force=False)

    flush(force=True)

    # Merge any trailing chunk that ended up too small into its
    # predecessor, per "merge very small paragraphs when appropriate".
    MIN_STANDALONE_TOKENS = 60
    merged: list[DocumentChunk] = []
    for chunk in chunks:
        if (
            merged
            and _estimate_tokens(chunk.text) < MIN_STANDALONE_TOKENS
            and merged[-1].page == chunk.page
        ):
            prev = merged[-1]
            prev.text = f"{prev.text}\n\n{chunk.text}"
            prev.word_count = len(prev.text.split())
        else:
            merged.append(chunk)

    for i, chunk in enumerate(merged):
        chunk.previous_chunk_id = merged[i - 1].local_id if i > 0 else None
        chunk.next_chunk_id = merged[i + 1].local_id if i < len(merged) - 1 else None

    return merged

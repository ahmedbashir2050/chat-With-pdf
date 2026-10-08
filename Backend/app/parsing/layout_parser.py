"""Layout-aware parsing. Replaces plain `page.get_text()` extraction with
`page.get_text("dict")`, which gives us blocks -> lines -> spans with
font size, font flags (bold/italic), and bounding boxes intact — the
input hierarchy.py needs to tell "Chapter 3" from a regular paragraph,
and semantic_chunker.py needs to avoid splitting mid-paragraph.
"""

from dataclasses import dataclass, field

import fitz  # PyMuPDF

# PyMuPDF span "flags" bit 4 (value 16) marks bold-ish weight; see the
# PyMuPDF docs on `get_text("dict")` span flags.
_BOLD_FLAG = 1 << 4


@dataclass
class LayoutBlock:
    """One text block on a page, in reading order as PyMuPDF emits it
    (top-to-bottom, then left-to-right within a row of columns)."""

    page: int  # 1-based physical page number
    block_index: int  # 0-based order within the page as emitted by PyMuPDF
    text: str
    bbox: tuple[float, float, float, float]
    max_font_size: float
    avg_font_size: float
    is_bold: bool
    column: int = 0  # 0 = single/left column, 1 = right column (see _assign_columns)


@dataclass
class LayoutPage:
    page: int
    width: float
    height: float
    blocks: list[LayoutBlock] = field(default_factory=list)
    is_two_column: bool = False


def _block_text(block: dict) -> str:
    lines = []
    for line in block.get("lines", []):
        spans_text = "".join(span.get("text", "") for span in line.get("spans", []))
        if spans_text.strip():
            lines.append(spans_text)
    return "\n".join(lines).strip()


def _font_stats(block: dict) -> tuple[float, float, bool]:
    sizes = []
    bold_votes = 0
    span_count = 0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if not span.get("text", "").strip():
                continue
            sizes.append(span.get("size", 0.0))
            span_count += 1
            if span.get("flags", 0) & _BOLD_FLAG:
                bold_votes += 1
            # Many PDFs encode weight in the font name rather than flags.
            font_name = span.get("font", "").lower()
            if "bold" in font_name or "black" in font_name or "heavy" in font_name:
                bold_votes += 1

    if not sizes:
        return 0.0, 0.0, False
    return max(sizes), sum(sizes) / len(sizes), bold_votes >= max(1, span_count // 2)


def _assign_columns(blocks: list[LayoutBlock], page_width: float) -> bool:
    """Heuristic two-column detection: if a meaningful fraction of blocks
    sit entirely within the left half or entirely within the right half
    (rather than spanning the page width), treat the page as two-column
    and tag each block accordingly so the chunker can reorder into
    correct reading order (left column top-to-bottom, then right column)
    instead of PyMuPDF's raw top-to-bottom-across-the-whole-page order,
    which interleaves the two columns incorrectly."""
    if not blocks:
        return False

    midpoint = page_width / 2
    left_only = 0
    right_only = 0
    spanning = 0

    for b in blocks:
        x0, _, x1, _ = b.bbox
        if x1 <= midpoint + (page_width * 0.05):
            left_only += 1
        elif x0 >= midpoint - (page_width * 0.05):
            right_only += 1
        else:
            spanning += 1

    is_two_column = left_only >= 2 and right_only >= 2 and spanning <= max(2, len(blocks) // 4)

    if is_two_column:
        for b in blocks:
            x0, _, x1, _ = b.bbox
            b.column = 1 if x0 >= midpoint - (page_width * 0.05) else 0
        blocks.sort(key=lambda b: (b.column, b.bbox[1], b.bbox[0]))

    return is_two_column


def parse_page_layout(page: "fitz.Page", page_number: int) -> LayoutPage:
    """page_number is 1-based, matching the rest of the app's convention
    (see DocumentChunk.page)."""
    raw = page.get_text("dict")
    blocks: list[LayoutBlock] = []

    for i, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:  # 0 = text block, 1 = image block
            continue
        text = _block_text(block)
        if not text:
            continue
        max_size, avg_size, is_bold = _font_stats(block)
        blocks.append(
            LayoutBlock(
                page=page_number,
                block_index=i,
                text=text,
                bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
                max_font_size=max_size,
                avg_font_size=avg_size,
                is_bold=is_bold,
            )
        )

    layout_page = LayoutPage(page=page_number, width=page.rect.width, height=page.rect.height, blocks=blocks)
    layout_page.is_two_column = _assign_columns(blocks, page.rect.width)
    return layout_page

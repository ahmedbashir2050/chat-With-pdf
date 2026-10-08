"""Document hierarchy detection. Classifies each `LayoutBlock` into a
`HierarchyLevel` using font-size percentile within the document, bold
weight, position, and a few regex patterns for explicit "Chapter N" /
"الفصل ن" markers — then folds the classified blocks into a nested
`HierarchyNode` tree.

This is intentionally a heuristic layer, not a layout-ML model: font size
relative to the document's own body-text size is a strong, cheap signal
(a 24pt block in a document whose body text is 10pt is a heading whether
or not the author also bolded it), and it degrades gracefully — a
document with no discernible heading structure just produces a flat list
of PARAGRAPH-level blocks, which the chunker still handles fine.
"""

import re
import statistics
from dataclasses import dataclass

from .layout_parser import LayoutBlock
from .models import HierarchyLevel, HierarchyNode

_CHAPTER_RE = re.compile(r"^\s*(chapter|الفصل|فصل)\s+\S+", re.IGNORECASE)
_SECTION_NUMBER_RE = re.compile(r"^\s*\d+(\.\d+){0,3}\s+\S")  # "2.1 Background", "3 Methods"
_LIST_ITEM_RE = re.compile(r"^\s*(([-•*–]|\d+[.)]|[a-zA-Z][.)])\s+)")

MAX_HEADING_WORDS = 20  # a block this long is a paragraph even if it's bold/large


@dataclass
class ClassifiedBlock:
    block: LayoutBlock
    level: HierarchyLevel


def _document_body_size(blocks: list[LayoutBlock]) -> float:
    """The most common avg_font_size across all blocks — treated as the
    document's body-text size, against which everything else is judged
    relatively large or small. Falls back to the median when there's no
    clear mode (e.g. a very short document)."""
    sizes = [round(b.avg_font_size, 1) for b in blocks if b.avg_font_size > 0]
    if not sizes:
        return 10.0
    try:
        return statistics.mode(sizes)
    except statistics.StatisticsError:
        return statistics.median(sizes)


def _classify_block(block: LayoutBlock, body_size: float, word_count: int) -> HierarchyLevel:
    text = block.text.strip()
    size_ratio = (block.max_font_size / body_size) if body_size else 1.0

    if _LIST_ITEM_RE.match(text):
        return HierarchyLevel.LIST_ITEM

    if _CHAPTER_RE.match(text) and word_count <= MAX_HEADING_WORDS:
        return HierarchyLevel.CHAPTER

    # Large/bold + short text is the general heading signal; the exact
    # level is inferred from *how* large relative to body text, since
    # documents rarely label "Subsection" explicitly.
    looks_heading = (size_ratio >= 1.15 or block.is_bold) and word_count <= MAX_HEADING_WORDS
    if not looks_heading:
        return HierarchyLevel.PARAGRAPH

    if size_ratio >= 1.8:
        return HierarchyLevel.TITLE
    if size_ratio >= 1.5:
        return HierarchyLevel.CHAPTER
    if size_ratio >= 1.3:
        return HierarchyLevel.SECTION
    if size_ratio >= 1.15:
        return HierarchyLevel.SUBSECTION
    # Bold-but-not-larger-than-body text (e.g. a bolded run-in heading).
    return HierarchyLevel.HEADING


def classify_blocks(all_blocks: list[LayoutBlock]) -> list[ClassifiedBlock]:
    """Classifies every block across the whole document at once (not
    page-by-page) so the body-text-size baseline reflects the document as
    a whole rather than resetting per page."""
    body_size = _document_body_size(all_blocks)
    result = []
    for block in all_blocks:
        word_count = len(block.text.split())
        level = _classify_block(block, body_size, word_count)
        result.append(ClassifiedBlock(block=block, level=level))
    return result


_LEVEL_RANK = {
    HierarchyLevel.TITLE: 0,
    HierarchyLevel.CHAPTER: 1,
    HierarchyLevel.SECTION: 2,
    HierarchyLevel.SUBSECTION: 3,
    HierarchyLevel.HEADING: 4,
    HierarchyLevel.PARAGRAPH: 5,
    HierarchyLevel.LIST_ITEM: 5,
}


def build_hierarchy_tree(classified: list[ClassifiedBlock]) -> list[HierarchyNode]:
    """Folds the flat, classified, reading-order block list into a nested
    tree by heading rank: each heading becomes a node whose children are
    every subsequent block of a strictly deeper (or equal-and-following)
    rank, up to the next heading at the same or shallower rank."""
    roots: list[HierarchyNode] = []
    # stack of (rank, node) — the current open ancestry chain
    stack: list[tuple[int, HierarchyNode]] = []

    for item in classified:
        rank = _LEVEL_RANK[item.level]
        node = HierarchyNode(
            level=item.level,
            text=item.block.text[:300],
            page=item.block.page,
            bbox=None,
        )
        from .models import BoundingBox

        node.bbox = BoundingBox.from_tuple(item.block.bbox)

        if item.level in (HierarchyLevel.PARAGRAPH, HierarchyLevel.LIST_ITEM):
            # Attach body content to the deepest open heading, if any;
            # otherwise it's front matter with no heading yet — surface
            # it as a root-level node so nothing is silently dropped.
            if stack:
                stack[-1][1].children.append(node)
            else:
                roots.append(node)
            continue

        while stack and _LEVEL_RANK[stack[-1][1].level] >= rank:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((rank, node))

    return roots


def current_context(
    classified_so_far: list[ClassifiedBlock],
) -> dict[str, str | None]:
    """Given the blocks seen so far (in reading order), returns the most
    recent chapter/section/subsection/heading text — the "where are we"
    context attached to each chunk during semantic chunking."""
    context: dict[str, str | None] = {
        "chapter": None,
        "section": None,
        "subsection": None,
        "heading": None,
    }
    for item in classified_so_far:
        if item.level == HierarchyLevel.CHAPTER:
            context["chapter"] = item.block.text.strip()
            context["section"] = None
            context["subsection"] = None
        elif item.level == HierarchyLevel.SECTION:
            context["section"] = item.block.text.strip()
            context["subsection"] = None
        elif item.level == HierarchyLevel.SUBSECTION:
            context["subsection"] = item.block.text.strip()
        elif item.level == HierarchyLevel.HEADING:
            context["heading"] = item.block.text.strip()
    return context

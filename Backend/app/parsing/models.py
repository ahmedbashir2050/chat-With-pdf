"""Document-intelligence models introduced in Phase 2.

These are pure data containers (Pydantic, not SQLAlchemy) describing the
*structure* PyMuPDF gives us before it gets flattened into the
`DocumentChunk` rows the rest of the app (embedding, retrieval, prompting)
already knows how to work with. `ParsedDocument` is the new top-level
return type of the document-intelligence parser; `adapter.py` is what
flattens it back into the shape `ChatService`/`ChunkRepository` expect, so
nothing downstream of parsing has to change.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..domain.entities import DocumentChunk


class ChunkType(str, Enum):
    TITLE = "title"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    MIXED = "mixed"  # a merged chunk spanning more than one block type


class HierarchyLevel(str, Enum):
    """Classification applied to an individual layout block, before
    chunking groups blocks together. A superset of ChunkType because a
    block can be a plain paragraph that never becomes its own chunk."""

    TITLE = "title"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_tuple(cls, rect: tuple[float, float, float, float]) -> "BoundingBox":
        return cls(x0=rect[0], y0=rect[1], x1=rect[2], y1=rect[3])


class DocumentMetadata(BaseModel):
    document_id: str
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None
    page_count: int
    language: str | None = None  # primary document language: 'ar' | 'en' | 'mixed' | None
    creation_date: str | None = None
    modification_date: str | None = None


class HierarchyNode(BaseModel):
    """One node in the document tree (title/chapter/section/.../paragraph).
    `children` lets this represent the full nested structure described in
    the spec; `chunk_ids` is filled in after semantic chunking so callers
    can go from "Chapter 3" back to the chunks that belong to it."""

    level: HierarchyLevel
    text: str
    page: int
    bbox: BoundingBox | None = None
    children: list["HierarchyNode"] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


HierarchyNode.model_rebuild()


class TableElement(BaseModel):
    page: int
    bbox: BoundingBox
    markdown_content: str
    related_section: str | None = None


class ImageElement(BaseModel):
    page: int
    bbox: BoundingBox
    image_index: int
    image_path: str | None = None
    image_bytes_ref: str | None = None  # opaque reference (e.g. storage key) when not written to disk
    nearby_text: str | None = None
    related_section: str | None = None


class ParsedPage(BaseModel):
    """Per-page summary kept alongside the flat chunk/table/image lists —
    useful for anything that wants a page-by-page view without walking
    the whole hierarchy tree.

    `classification`/`quality_status`/`quality_score`/`quality_warnings`/
    `retry_count`/`source_type` are the page-classification + quality-gate
    outputs (parsing/page_classifier.py, parsing/quality_gate.py). All
    default to values that describe "a normal native page, no issues" so
    existing construction sites (and the pre-quality-gate `has_ocr_fallback`
    flag some callers may still check) keep working unmodified.
    """

    page: int
    page_label: str | None = None
    language: str | None = None
    is_two_column: bool = False
    has_ocr_fallback: bool = False

    classification: str = "native"  # page_classifier.PageClass value
    quality_status: str = "accepted"  # quality_gate.QualityStatus value
    quality_score: float | None = None
    quality_warnings: list[str] = Field(default_factory=list)
    retry_count: int = 0
    retry_reasons: list[str] = Field(default_factory=list)
    source_type: str = "native"  # quality_gate.SourceType value
    excluded_from_rag: bool = False  # true if this page's content was left out of chunking/embedding
    raw_text: str | None = None  # populated only when excluded_from_rag=True, for manual review — never chunked/embedded


class ParsedDocument(BaseModel):
    """Top-level output of the document-intelligence parser. Nothing in
    the existing API contract returns this directly — `adapter.py`
    flattens it into `list[DocumentChunk]` for `ChatService`, so this
    type is purely internal to the parsing pipeline (and available to
    anything in a future phase that wants the richer structure, e.g. a
    document-outline endpoint)."""

    metadata: DocumentMetadata
    pages: list[ParsedPage]
    hierarchy: list[HierarchyNode]
    chunks: list[DocumentChunk] = Field(default_factory=list)
    tables: list[TableElement] = Field(default_factory=list)
    images: list[ImageElement] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

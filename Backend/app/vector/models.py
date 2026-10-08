"""Plain, framework-light types for the vector layer. These are distinct
from `qdrant_client.models` (the wire-format types the client library
itself defines) so the rest of the app never imports `qdrant_client`
directly outside of `client.py`/`repository.py` — swapping Qdrant for a
different vector database later only touches this package.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    """One point to upsert into the collection: a chunk's embedding plus
    every payload field we want filterable or returnable without a round
    trip back to SQLite."""

    id: int
    vector: list[float]
    chat_id: int
    document_id: str | None = None
    page: int | None = None  # the physical, 1-based PDF page index — the only page field citations use
    chapter: str | None = None
    section: str | None = None
    heading: str | None = None
    language: str | None = None
    chunk_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "chunk_id": self.id,
            "chat_id": self.chat_id,
            "document_id": self.document_id,
            "page": self.page,
            "chapter": self.chapter,
            "section": self.section,
            "heading": self.heading,
            "language": self.language,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class VectorSearchResult:
    """One hit from a Qdrant nearest-neighbor search, translated out of
    Qdrant's wire format."""

    chunk_id: int
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchFilter:
    """The subset of payload filters the search API supports pushing
    down into Qdrant (spec item 8: metadata filtering). All fields are
    optional and combined with AND semantics; `None` means "don't filter
    on this field". `chunk_ids`, when given, restricts the search to an
    explicit candidate set — used by `QdrantVectorStore` to stay
    compatible with callers that pre-filter a pool in Python (see
    vectorstore/qdrant_vector_store.py) without requiring every caller to
    be rewritten against payload filters immediately.
    """

    chat_id: int | None = None
    document_id: str | None = None
    chapter: str | None = None
    section: str | None = None
    page: int | None = None
    language: str | None = None
    chunk_type: str | None = None
    chunk_ids: tuple[int, ...] | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.chat_id is not None,
                self.document_id is not None,
                self.chapter is not None,
                self.section is not None,
                self.page is not None,
                self.language is not None,
                self.chunk_type is not None,
                self.chunk_ids is not None,
            )
        )


@dataclass(frozen=True)
class CollectionConfig:
    """Collection/index configuration, sourced from `Settings` (spec
    items 4-5) rather than hardcoded so tuning HNSW parameters or vector
    size never requires a code change."""

    name: str
    vector_size: int
    distance: str = "cosine"  # 'cosine' | 'dot' | 'euclid'
    hnsw_m: int = 16
    hnsw_ef_construct: int = 128
    search_ef: int = 128

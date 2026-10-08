"""`QdrantService` — the one type the rest of the application depends on
for anything vector-related. Wraps `QdrantRepository` with:

- lazy collection initialization (spec item 13),
- batching for large upsert/delete calls (spec item 12),
- a thin async facade (`asyncio.to_thread`) so callers in async request
  handlers don't block the event loop on the underlying sync HTTP calls
  the qdrant-client makes (spec item 13: "async support where possible" —
  qdrant-client also ships a native `AsyncQdrantClient`; wrapping the sync
  client here instead keeps `client.py`/`repository.py` retry logic in
  one place rather than duplicating it for two client classes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .exceptions import VectorDatabaseError
from .models import CollectionConfig, VectorRecord, VectorSearchFilter, VectorSearchResult

if TYPE_CHECKING:
    # Only needed for the type hint below; importing it at runtime would
    # pull in `qdrant_client` (repository.py's one real dependency)
    # everywhere QdrantService is imported, including in unit tests that
    # inject a fake/duck-typed repository and shouldn't need the actual
    # qdrant-client package installed. See tests/test_qdrant_service.py.
    from .repository import QdrantRepository

logger = logging.getLogger(__name__)

# Points per upsert/delete-by-id call — keeps individual HTTP payloads a
# reasonable size for very large documents (spec item 12) without the
# caller needing to think about chunking.
DEFAULT_BATCH_SIZE = 256


class QdrantService:
    def __init__(self, repository: "QdrantRepository", collection: CollectionConfig, batch_size: int = DEFAULT_BATCH_SIZE):
        self._repo = repository
        self._collection = collection
        self._batch_size = batch_size
        self._initialized = False

    @property
    def collection_name(self) -> str:
        return self._collection.name

    # ---------------- Lazy initialization ----------------

    def ensure_ready(self) -> None:
        """Idempotent; safe to call before every operation. Cheap after
        the first call since `collection_exists` is a fast metadata
        lookup, but callers that want to avoid even that should call it
        once at startup (see api/deps.py) instead of per-request."""
        if self._initialized:
            return
        self._repo.ensure_collection(self._collection)
        self._initialized = True

    # ---------------- Upsert ----------------

    def upsert_many(self, records: list[VectorRecord]) -> None:
        self.ensure_ready()
        for i in range(0, len(records), self._batch_size):
            batch = records[i : i + self._batch_size]
            self._validate_dimensions(batch)
            self._repo.upsert(self._collection.name, batch)

    def upsert_one(self, record: VectorRecord) -> None:
        self.upsert_many([record])

    async def upsert_many_async(self, records: list[VectorRecord]) -> None:
        await asyncio.to_thread(self.upsert_many, records)

    # ---------------- Delete ----------------

    def delete_by_ids(self, chunk_ids: list[int]) -> None:
        self.ensure_ready()
        for i in range(0, len(chunk_ids), self._batch_size):
            self._repo.delete_by_ids(self._collection.name, chunk_ids[i : i + self._batch_size])

    def delete_for_chat(self, chat_id: int) -> None:
        """Used by the chat-delete and PDF-replace pipelines (spec items
        10-11) — a single filter-based delete rather than fetching every
        chunk id first, and the only path that guarantees no orphan
        vectors survive a chat deletion."""
        self.ensure_ready()
        self._repo.delete_by_filter(self._collection.name, VectorSearchFilter(chat_id=chat_id))

    async def delete_for_chat_async(self, chat_id: int) -> None:
        await asyncio.to_thread(self.delete_for_chat, chat_id)

    def replace_for_chat(self, chat_id: int, records: list[VectorRecord]) -> None:
        """Delete-then-insert for the "PDF replaced" pipeline (spec item
        11). Qdrant has no native multi-document transaction, so
        atomicity here means: delete completes before insert starts, and
        if insert fails partway the chat is left with no vectors (fails
        safely closed, not with a mix of old and new chunks) rather than
        silently mixing old/new content in search results."""
        self.delete_for_chat(chat_id)
        self.upsert_many(records)

    # ---------------- Search ----------------

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[VectorSearchResult]:
        self.ensure_ready()
        return self._repo.search(
            self._collection.name,
            query_vector,
            top_k=top_k,
            filters=filters,
            search_ef=self._collection.search_ef,
            expected_vector_size=self._collection.vector_size,
        )

    async def search_async(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[VectorSearchResult]:
        return await asyncio.to_thread(self.search, query_vector, top_k=top_k, filters=filters)

    # ---------------- Introspection (used by the migration tool) ----------------

    def count(self, filters: VectorSearchFilter | None = None) -> int:
        self.ensure_ready()
        return self._repo.count(self._collection.name, filters)

    # ---------------- Internal ----------------

    def _validate_dimensions(self, records: list[VectorRecord]) -> None:
        from .exceptions import EmbeddingDimensionMismatch

        for r in records:
            if len(r.vector) != self._collection.vector_size:
                raise EmbeddingDimensionMismatch(self._collection.vector_size, len(r.vector))


def try_or_none(fn, *, log_message: str):
    """Small helper for call sites that want graceful degradation (spec
    item 14) instead of a hard failure when the vector DB is down. Not
    used inside QdrantService itself (which should raise so the caller
    can decide), only by adapters like `QdrantVectorStore` that have a
    fallback available."""
    try:
        return fn()
    except VectorDatabaseError as exc:
        logger.warning("%s: %s", log_message, exc)
        return None

"""Keeps SQLite (chunk metadata + text) and Qdrant (vectors) in sync on
every write path, without touching `SqlAlchemyChunkRepository` itself.

Implemented as a decorator around the existing repository rather than by
editing it in place: `SqlAlchemyChunkRepository` still owns the SQLite
side exactly as before (backward compatible, and reusable anywhere a
Qdrant sync isn't wanted — e.g. tests), and this class adds "...and also
write the vectors" on top. `ChatService` (application/chat_service.py)
depends on this class instead, wired in at api/deps.py.
"""

from __future__ import annotations

from ..domain.entities import DocumentChunk
from ..domain.interfaces import ChunkRepository
from ..vector.exceptions import VectorDatabaseError
from ..vector.models import VectorRecord
from ..vector.service import QdrantService


def _to_vector_record(chunk: DocumentChunk) -> VectorRecord:
    return VectorRecord(
        id=chunk.id,
        vector=chunk.embedding or [],
        chat_id=chunk.chat_id,
        document_id=chunk.document_id,
        page=chunk.page,  # physical page only — see vector/models.py
        chapter=chunk.chapter,
        section=chunk.section,
        heading=chunk.heading,
        language=chunk.language,
        chunk_type=chunk.chunk_type,
        metadata={
            "subsection": chunk.subsection,
            "paragraph_index": chunk.paragraph_index,
            "word_count": chunk.word_count,
            "quality_status": chunk.quality_status,
            "source_type": chunk.source_type,
            "page_classification": chunk.page_classification,
        },
    )


class VectorSyncedChunkRepository:
    """Implements domain.interfaces.ChunkRepository."""

    def __init__(self, sql_repo: ChunkRepository, vector_service: QdrantService, *, fail_open: bool = True):
        self._sql = sql_repo
        self._vectors = vector_service
        # fail_open=True: a Qdrant outage degrades search quality (via
        # QdrantVectorStore's brute-force fallback) rather than blocking
        # uploads entirely. Set False in deployments where an unindexed
        # chunk is worse than a failed upload.
        self._fail_open = fail_open

    def save_many(self, chunks: list[DocumentChunk]) -> None:
        # SQLite first: this is what assigns each chunk's `id`, which the
        # vector records need as their point id.
        self._sql.save_many(chunks)

        records = [_to_vector_record(c) for c in chunks if c.embedding is not None]
        try:
            self._vectors.upsert_many(records)
        except VectorDatabaseError:
            if not self._fail_open:
                raise
            # Metadata is already committed; the chunk is simply
            # unreachable via Qdrant search until the next migration/backfill
            # run or a retried upsert. Logged inside QdrantService/repository.

    def delete_for_chat(self, chat_id: int) -> None:
        self._sql.delete_for_chat(chat_id)
        try:
            self._vectors.delete_for_chat(chat_id)
        except VectorDatabaseError:
            if not self._fail_open:
                raise
            # Orphan vectors may remain until the next migration tool run
            # reconciles counts (spec item 17) — logged, not silently ignored.

    def get_for_chat(self, chat_id: int) -> list[DocumentChunk]:
        return self._sql.get_for_chat(chat_id)

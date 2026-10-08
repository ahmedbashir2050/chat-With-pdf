"""Low-level Qdrant operations. `QdrantRepository` talks the Qdrant wire
protocol (collections, points, filters) and translates failures into the
exception types in `exceptions.py`. `QdrantService` (service.py) is the
layer application code actually depends on; this module exists so that
translation — and the `qdrant_client.models` imports it requires — stays
out of the service layer's business logic.
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    HnswConfigDiff,
    MatchAny,
    MatchValue,
    PointIdsList,
    PointStruct,
    ScoredPoint,
    SearchParams,
    VectorParams,
)

from .client import with_retry
from .exceptions import (
    CollectionNotFound,
    EmbeddingDimensionMismatch,
    SearchFailed,
    VectorDeleteFailed,
    VectorInsertFailed,
)
from .models import CollectionConfig, VectorRecord, VectorSearchFilter, VectorSearchResult

_DISTANCE_MAP = {
    "cosine": Distance.COSINE,
    "dot": Distance.DOT,
    "euclid": Distance.EUCLID,
}


class QdrantRepository:
    def __init__(self, client: QdrantClient, *, max_retries: int, retry_backoff_seconds: float):
        self._client = client
        self._max_retries = max_retries
        self._backoff = retry_backoff_seconds

    def _run(self, operation_name: str, fn):
        return with_retry(
            fn,
            max_retries=self._max_retries,
            backoff_seconds=self._backoff,
            operation_name=operation_name,
        )

    # ---------------- Collections ----------------

    def collection_exists(self, name: str) -> bool:
        return self._run("collection_exists", lambda: self._client.collection_exists(name))

    def create_collection(self, config: CollectionConfig) -> None:
        distance = _DISTANCE_MAP.get(config.distance.lower())
        if distance is None:
            raise ValueError(f"Unsupported distance metric: {config.distance!r}")

        self._run(
            "create_collection",
            lambda: self._client.create_collection(
                collection_name=config.name,
                vectors_config=VectorParams(size=config.vector_size, distance=distance),
                hnsw_config=HnswConfigDiff(m=config.hnsw_m, ef_construct=config.hnsw_ef_construct),
            ),
        )

    def ensure_collection(self, config: CollectionConfig) -> None:
        """Idempotent: creates the collection only if it doesn't already
        exist. Safe to call on every app startup (see api/deps.py)."""
        if not self.collection_exists(config.name):
            self.create_collection(config)

    # ---------------- Upsert / delete ----------------

    def upsert(self, collection_name: str, records: list[VectorRecord]) -> None:
        """Batch upsert — a single Qdrant call for the whole batch rather
        than one call per point (spec item 12: avoid inserting vectors
        one by one)."""
        if not records:
            return
        points = [PointStruct(id=r.id, vector=r.vector, payload=r.to_payload()) for r in records]
        try:
            self._run("upsert", lambda: self._client.upsert(collection_name=collection_name, points=points))
        except Exception as exc:
            raise VectorInsertFailed(f"Failed to upsert {len(records)} vector(s): {exc}") from exc

    def delete_by_ids(self, collection_name: str, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        try:
            self._run(
                "delete_by_ids",
                lambda: self._client.delete(
                    collection_name=collection_name,
                    points_selector=PointIdsList(points=chunk_ids),
                ),
            )
        except Exception as exc:
            raise VectorDeleteFailed(f"Failed to delete {len(chunk_ids)} vector(s) by id: {exc}") from exc

    def delete_by_filter(self, collection_name: str, filters: VectorSearchFilter) -> None:
        qfilter = _build_filter(filters)
        if qfilter is None:
            raise VectorDeleteFailed("Refusing to run an unfiltered delete-all; provide at least one filter field.")
        try:
            self._run(
                "delete_by_filter",
                lambda: self._client.delete(
                    collection_name=collection_name,
                    points_selector=FilterSelector(filter=qfilter),
                ),
            )
        except Exception as exc:
            raise VectorDeleteFailed(f"Failed to delete vectors matching filter: {exc}") from exc

    # ---------------- Search ----------------

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None,
        search_ef: int | None = None,
        expected_vector_size: int | None = None,
    ) -> list[VectorSearchResult]:
        if expected_vector_size is not None and len(query_vector) != expected_vector_size:
            raise EmbeddingDimensionMismatch(expected_vector_size, len(query_vector))

        qfilter = _build_filter(filters) if filters else None
        search_params = SearchParams(hnsw_ef=search_ef) if search_ef else None

        try:
            # `QdrantClient.search()` is deprecated as of qdrant-client
            # 1.10 and REMOVED entirely in recent client releases (hence
            # the "'QdrantClient' object has no attribute 'search'"
            # failure this replaced) — `query_points()` is the current
            # Query API and is what every supported client version now
            # exposes. Same semantics for a plain nearest-neighbor
            # lookup: `query=<vector>` takes the place of the old
            # `query_vector=<vector>`, and the scored points come back
            # as `response.points` instead of directly as the return
            # value.
            response = self._run(
                "search",
                lambda: self._client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    query_filter=qfilter,
                    limit=top_k,
                    search_params=search_params,
                    with_payload=True,
                ),
            )
            points: list[ScoredPoint] = response.points
        except Exception as exc:
            if "doesn't exist" in str(exc).lower() or "not found" in str(exc).lower():
                raise CollectionNotFound(f"Collection '{collection_name}' not found: {exc}") from exc
            raise SearchFailed(f"Vector search failed: {exc}") from exc

        return [
            VectorSearchResult(chunk_id=p.payload.get("chunk_id", p.id), score=p.score, payload=p.payload or {})
            for p in points
        ]

    def count(self, collection_name: str, filters: VectorSearchFilter | None = None) -> int:
        qfilter = _build_filter(filters) if filters else None
        result = self._run(
            "count",
            lambda: self._client.count(collection_name=collection_name, count_filter=qfilter, exact=True),
        )
        return result.count


def _build_filter(filters: VectorSearchFilter | None) -> Filter | None:
    if filters is None or filters.is_empty():
        return None

    must: list[FieldCondition] = []
    if filters.chat_id is not None:
        must.append(FieldCondition(key="chat_id", match=MatchValue(value=filters.chat_id)))
    if filters.document_id is not None:
        must.append(FieldCondition(key="document_id", match=MatchValue(value=filters.document_id)))
    if filters.chapter is not None:
        must.append(FieldCondition(key="chapter", match=MatchValue(value=filters.chapter)))
    if filters.section is not None:
        must.append(FieldCondition(key="section", match=MatchValue(value=filters.section)))
    if filters.page is not None:
        must.append(FieldCondition(key="page", match=MatchValue(value=filters.page)))
    if filters.language is not None:
        must.append(FieldCondition(key="language", match=MatchValue(value=filters.language)))
    if filters.chunk_type is not None:
        must.append(FieldCondition(key="chunk_type", match=MatchValue(value=filters.chunk_type)))
    if filters.chunk_ids is not None:
        must.append(FieldCondition(key="chunk_id", match=MatchAny(any=list(filters.chunk_ids))))

    return Filter(must=must) if must else None

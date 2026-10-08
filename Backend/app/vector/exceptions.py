"""Custom exceptions for the Qdrant-backed vector database layer.

Kept as a small, flat hierarchy rooted in `VectorDatabaseError` so callers
that just want "something in the vector layer went wrong" can catch one
type, while call sites that need to react differently (e.g. fall back to
brute-force search only on connectivity failure, not on a programming
error) can catch the specific subclass.
"""


class VectorDatabaseError(Exception):
    """Base class for all vector-layer errors."""


class VectorDatabaseUnavailable(VectorDatabaseError):
    """Qdrant could not be reached (connection refused, timeout, DNS
    failure, etc.) after retries were exhausted. Distinguished from other
    errors because it's the one case callers may reasonably want to
    degrade gracefully (see vectorstore/qdrant_vector_store.py) rather
    than fail the request outright."""


class CollectionNotFound(VectorDatabaseError):
    """The configured collection does not exist and auto-creation was
    not requested or failed."""


class EmbeddingDimensionMismatch(VectorDatabaseError):
    """A vector's dimensionality does not match the collection's
    configured vector size (`QDRANT_VECTOR_SIZE`). Almost always means
    the embedding model was changed without a matching migration."""

    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Expected vector of size {expected}, got {actual}.")


class VectorInsertFailed(VectorDatabaseError):
    """An upsert (single or batch) did not complete successfully."""


class VectorDeleteFailed(VectorDatabaseError):
    """A delete (single or batch/filter-based) did not complete
    successfully."""


class SearchFailed(VectorDatabaseError):
    """A search request failed for a reason other than the database
    being unreachable (e.g. malformed filter, invalid vector size)."""

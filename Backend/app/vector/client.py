"""Reusable Qdrant client construction.

Isolated in its own module — nothing outside `app/vector/` imports
`qdrant_client` directly — so the rest of the codebase depends only on
`QdrantService` (service.py). `qdrant-client` itself already keeps a
pooled `httpx`/`grpc` connection under the hood, so "connection pooling"
here means: build the client once as a singleton (see api/deps.py) and
reuse it, rather than opening a new connection per request.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from qdrant_client import QdrantClient

from .exceptions import VectorDatabaseUnavailable

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class QdrantConnectionConfig:
    """Everything needed to open a connection, read straight from
    `Settings` (see config.py) so `local` / `docker` / `cloud` deployments
    only differ in environment variables, never in code."""

    url: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: str | None = None
    https: bool = False
    timeout: float = 10.0
    prefer_grpc: bool = False
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5


def build_qdrant_client(config: QdrantConnectionConfig) -> QdrantClient:
    """Constructs the underlying `qdrant_client.QdrantClient`. Cheap and
    lazy — the constructor itself does not open a network connection, so
    this is safe to call eagerly at process startup (module-level
    singleton in api/deps.py) without delaying app boot if Qdrant happens
    to be down; the first real request will retry via `with_retry`."""
    return QdrantClient(
        url=config.url,
        port=config.port,
        grpc_port=config.grpc_port,
        api_key=config.api_key,
        https=config.https,
        timeout=config.timeout,
        prefer_grpc=config.prefer_grpc,
    )


def with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int,
    backoff_seconds: float,
    operation_name: str,
) -> T:
    """Runs `fn`, retrying on connection-level failures with linear
    backoff. Only network/availability failures are retried — a bad
    filter or dimension mismatch is a programming error that retrying
    won't fix, so those exceptions are expected to be raised as-is by
    `fn` and are not caught here (repository.py/service.py are
    responsible for translating them into the specific exception types
    in exceptions.py before they reach this helper, or after it re-raises
    `VectorDatabaseUnavailable`).
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except (AttributeError, TypeError) as exc:
            # Not a transient connectivity failure — a missing attribute
            # or bad call signature means the installed qdrant-client
            # version doesn't have the method/parameter being called
            # (e.g. `.search()` was removed in favor of `.query_points()`
            # in recent client releases), or there's a genuine
            # programming bug. Retrying the exact same call three times
            # can never fix either of those, and doing so just buries
            # the real error under misleading "operation failed, retrying"
            # warnings that look like a Qdrant outage. Fail immediately
            # with the original exception intact.
            logger.error(
                "Qdrant operation '%s' failed with a non-retryable error (likely a qdrant-client "
                "version/API mismatch, not a connectivity issue): %s",
                operation_name,
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - intentionally broad; see below
            # qdrant-client raises a mix of httpx/grpc transport errors
            # depending on transport mode. Rather than enumerate every
            # possible transport exception class (which would silently
            # go stale if the client library changes its exception
            # types), treat any failure to complete the call as a
            # potential connectivity issue and retry, giving up after
            # `max_retries` and surfacing a single, stable exception type
            # to the rest of the app.
            last_error = exc
            logger.warning(
                "Qdrant operation '%s' failed (attempt %d/%d): %s",
                operation_name,
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                time.sleep(backoff_seconds * attempt)

    raise VectorDatabaseUnavailable(
        f"Qdrant operation '{operation_name}' failed after {max_retries} attempts."
    ) from last_error

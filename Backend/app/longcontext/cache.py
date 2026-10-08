"""Caching for long-context outputs (spec item 13) — chapter/section/
document summaries, explanations, and outlines are all expensive
(multiple LLM calls for a large chapter) and completely deterministic
inputs-wise within one document version, so recomputing them for a
repeated identical request wastes the map-reduce cost entirely. Same
fingerprint-based invalidation pattern as `retrieval.keyword_search.
KeywordIndexCache`: keyed on chat_id + a cheap signature of the chunk
set actually used, so a re-upload (different chunk ids) naturally
invalidates stale entries without needing an explicit cache-clear call
anywhere in ChatService's replace_resource path.
"""

from ..domain.entities import DocumentChunk


def _fingerprint(chunks: list[DocumentChunk]) -> tuple:
    return tuple(c.id if c.id is not None else id(c) for c in chunks)


class LongContextCache:
    def __init__(self, max_entries: int = 500):
        self._cache: dict[tuple, tuple[tuple, object]] = {}
        self._max_entries = max_entries

    def get(self, chat_id: int, scope_key: tuple, chunks: list[DocumentChunk]):
        cache_key = (chat_id, scope_key)
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        fingerprint, value = entry
        if fingerprint != _fingerprint(chunks):
            return None
        return value

    def set(self, chat_id: int, scope_key: tuple, chunks: list[DocumentChunk], value) -> None:
        cache_key = (chat_id, scope_key)
        if len(self._cache) >= self._max_entries and cache_key not in self._cache:
            self._cache.pop(next(iter(self._cache)))  # evict oldest
        self._cache[cache_key] = (_fingerprint(chunks), value)

    def invalidate_chat(self, chat_id: int) -> None:
        stale_keys = [k for k in self._cache if k[0] == chat_id]
        for k in stale_keys:
            del self._cache[k]

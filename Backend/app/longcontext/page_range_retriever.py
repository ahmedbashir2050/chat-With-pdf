"""PageRangeRetriever (spec item 3)."""

from ..domain.entities import DocumentChunk


class PageRangeRetriever:
    def retrieve_range(self, start_page: int, end_page: int, all_chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        matched = [c for c in all_chunks if start_page <= c.page <= end_page]
        return sorted(matched, key=lambda c: (c.page, c.paragraph_index if c.paragraph_index is not None else 0))

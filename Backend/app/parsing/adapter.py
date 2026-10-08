"""Compatibility layer between the new `ParsedDocument` structure and the
existing API contract. `DocumentParser.extract_chunks` is a required part
of `domain.interfaces.DocumentParser` — everything downstream (ChatService,
ChunkRepository, the /chats and /chats/{id}/resource endpoints) is built
against "a document parses into `list[DocumentChunk]`". Since
`DocumentChunk` itself was extended (not replaced) to carry the new
metadata, this adapter's job is deliberately simple: hand back
`parsed.chunks` as-is. Nothing is lost — chapter/section/heading/bbox/
language/etc. all travel with each chunk already.

Kept as its own module (rather than inlined into document_parser_v2.py)
so the "old shape in, old shape out" contract is explicit and easy to
find/test on its own, and so a future second parser implementation can
reuse it.
"""

from ..domain.entities import DocumentChunk
from .models import ParsedDocument


def to_legacy_chunks(parsed: ParsedDocument) -> list[DocumentChunk]:
    """Returns the flat chunk list `ChatService._process_pdf` expects.
    The chunks already carry the Phase 2 metadata fields — callers that
    only look at `.chat_id`, `.page`, `.page_label`, `.text` (the Phase 1
    contract) are unaffected; callers that want the richer fields can
    read them off the same objects."""
    return list(parsed.chunks)


def tables_as_context_notes(parsed: ParsedDocument) -> dict[int, list[str]]:
    """Groups extracted tables by page, rendered as markdown — a helper
    for anything that wants to fold table content into prompt context by
    page without walking `parsed.tables` and filtering itself."""
    by_page: dict[int, list[str]] = {}
    for table in parsed.tables:
        by_page.setdefault(table.page, []).append(table.markdown_content)
    return by_page

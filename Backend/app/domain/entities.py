"""Domain entities — framework-agnostic. No FastAPI, SQLAlchemy, or OpenAI
imports here; these are the plain Python types the rest of the system
speaks in. Chat/User/Message stay as SQLAlchemy models for now (see
storage/repositories.py) — DocumentChunk is the one type promoted to a
full domain entity in this phase, since it's what actually flows through
parsing → embedding → retrieval → prompting. Promoting Chat/User/Message
the same way is a reasonable future refinement, not required for this
phase's goals."""

from dataclasses import dataclass, field


@dataclass
class DocumentChunk:
    """A retrievable unit of a parsed document. `id` and `embedding` are
    optional so this type can represent a freshly parsed chunk that hasn't
    been persisted/embedded yet, as well as one loaded back from storage.

    Phase 2 (document intelligence) extends this with structural metadata
    — chapter/section/heading context, position, language, chunk linkage,
    etc. All new fields are optional and default to None/empty so every
    pre-Phase-2 call site (`DocumentChunk(chat_id=..., page=..., ...)`)
    keeps working without modification; the simple fixed-size parser
    still produces valid chunks, just with the new fields left unset."""

    chat_id: int
    page: int  # the physical, 1-based PDF page index — the ONLY page field citations are ever built from
    page_label: str | None  # a detected printed page label (e.g. "12", "iv", "ج"), if any — NEVER used for
    # citations (see domain/citations.py). The production parser no longer auto-populates this onto chunks
    # (nothing currently consumes it there); kept as a settable field so tests can prove a chunk with a
    # DIFFERENT page_label than its physical page still cites the physical page, not the label.
    text: str
    id: int | None = None
    embedding: list[float] | None = None

    # --- Phase 2: rich chunk metadata (see parsing/models.py) ---
    document_id: str | None = None
    chapter: str | None = None
    section: str | None = None
    subsection: str | None = None
    heading: str | None = None
    paragraph_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    language: str | None = None
    word_count: int | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    chunk_type: str | None = None  # see parsing.models.ChunkType — kept as plain str here
    # so this stays a framework/parsing-layer-agnostic dataclass.

    # --- OCR/extraction quality provenance (parsing/quality_gate.py) ---
    # Plain str mirrors of quality_gate.QualityStatus / .SourceType /
    # page_classifier.PageClass values, kept as str here for the same
    # reason chunk_type is: this dataclass stays framework/parsing-layer
    # agnostic. All default to None so every existing call site
    # (`DocumentChunk(chat_id=..., page=..., ...)`) is unaffected.
    quality_status: str | None = None  # 'accepted' | 'needs_retry' | 'needs_review' | 'failed'
    source_type: str | None = None  # 'native' | 'ocr' | 'mixed'
    page_classification: str | None = None  # 'native' | 'scanned' | 'mixed' | 'corrupted' | 'empty'
    quality_score: float | None = None

    # Stable identifier assigned at parse time (before a DB id exists),
    # used to wire previous_chunk_id/next_chunk_id and hierarchy
    # chunk_ids together before the chunk has been persisted.
    local_id: str | None = field(default=None, repr=False)

    @property
    def citation_label(self) -> str:
        """The page identifier shown in a citation — ALWAYS the physical
        page index (str(self.page)). `page_label` (a detected printed
        page label, when the parser found one) deliberately has no
        influence here — see domain/citations.py's module docstring for
        why citations use physical_page only, never a printed label."""
        return str(self.page)

    @property
    def physical_page(self) -> int:
        """Alias for `page` under the name used by the citation contract
        (see domain/citations.py) — `page` is the field name used
        throughout parsing/storage/retrieval and stays as-is to avoid a
        ripple rename; `physical_page` is the explicit, unambiguous name
        citations are built from."""
        return self.page


@dataclass
class ScoredChunk:
    """A chunk plus how similar it was to some query — the unit retrieval
    operates on before deciding what to hand to the LLM."""

    chunk: DocumentChunk
    score: float

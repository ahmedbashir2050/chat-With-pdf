from datetime import datetime

from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    picture_url: str | None

    class Config:
        from_attributes = True


class GoogleAuthRequest(BaseModel):
    id_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChatOut(BaseModel):
    id: int
    title: str
    pdf_name: str
    created_at: datetime
    overview: str | None = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    question: str
    # Answer length is no longer a client-supplied field — the backend
    # infers it from the message itself (explicit phrasing, refinement
    # requests like "make that shorter", and question shape). See
    # query_understanding.infer_response_length(). Kept accepting any
    # extra fields silently (Pydantic's default) so older clients that
    # still send a response_length value don't break — it's just ignored.


class CitationOut(BaseModel):
    """`physical_page` is the ONLY page-identity field a citation
    carries — the 1-based physical PDF page index. There is
    deliberately no `page_label`/`display_page` field: a citation must
    always point at the physical page, never at a printed/roman-numeral
    label, so there is exactly one unambiguous page number a client can
    show as "[p. N]"."""

    document_id: str | None = None
    physical_page: int
    chapter: str | None = None
    section: str | None = None
    heading: str | None = None
    bbox: list[float] | None = None


class SendMessageResponse(BaseModel):
    reply: str  # kept for backward compatibility with clients built against Phase 1
    answer: str  # same value as `reply` — the key name the citation contract (Phase 2 Part 2) specifies
    citations: list[CitationOut] = []
    used_chunks: list[int | str | None] = []  # ids of every chunk actually sent to the LLM as context
    confidence_score: float = 1.0  # legacy: retrieval quality + citation-existence only, NOT factual correctness

    # --- Claim-level grounding metrics (additive, backward compatible) ---
    # retrieval_score: quality of the retrieved/reranked context (0..1).
    # evidence_coverage: fraction of factual claims in the final answer
    #   that had supporting document evidence.
    # citation_score: fraction of kept factual claims carrying a valid,
    #   existing page citation.
    # grounding_score: 0.50*evidence_coverage + 0.25*citation_score +
    #   0.25*retrieval_score — an engineering confidence/grounding
    #   metric, not a calibrated probability.
    retrieval_score: float = 1.0
    evidence_coverage: float = 1.0
    citation_score: float = 1.0
    grounding_score: float = 1.0

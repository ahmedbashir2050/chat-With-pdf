"""AnswerGeneratorService (spec item 6) — the single place that builds a
prompt, calls the LLM, and packages the result into the source-aware
response object (spec item 11). `QAService` delegates the "generate the
RAG answer" step to this class rather than doing it inline; `prompts.py`
itself is unchanged (only extended with an additive `answer_style`
parameter — see prompts.build_rag_system_prompt).

Streaming readiness (spec item 12, NOT implemented — architecture only):
`generate()` is split into three sub-steps (`_build_messages`,
`self._llm.complete(...)`, `_package_response`) specifically so a future
`generate_stream()` only needs to swap the middle step for a streaming
LLM call (e.g. `self._llm.complete_stream(...)`, yielding tokens) and
reuse `_build_messages` unchanged; `_package_response` would run once
against the accumulated final text after the stream ends. No streaming
LLM call exists yet — `domain/interfaces.LLMService` was deliberately
NOT extended with a stub method it can't fulfill; adding that interface
method is the actual first step of implementing streaming, left for
when it's built for real.
"""

from dataclasses import dataclass, field

from ..context.answer_style import STYLE_INSTRUCTIONS, classify_answer_style
from ..domain.citations import Citation, build_citations
from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService
from . import prompts
from .citation_validator_service import CitationValidatorService
from .claim_verification_service import ClaimVerificationService, GroundingReport

MAX_CITATIONS = 12


@dataclass
class GeneratedAnswer:
    """The spec's source-aware response object (item 11). `answer` is
    now the GROUNDED answer (after claim-level verification/repair) —
    what the model drafted is available on `grounding.original_answer`
    if a caller needs it. `confidence_score` keeps its original,
    unchanged meaning (retrieval quality + inline-citation-existence
    penalty) — spec item 7 explicitly requires NOT overloading that
    field with factual-correctness; the new grounding metrics live on
    `grounding` instead."""

    answer: str
    citations: list[Citation]
    used_chunks: list[int | str | None]
    confidence_score: float
    grounding: GroundingReport | None = field(default=None, repr=False)

    @property
    def evidence_coverage(self) -> float:
        return self.grounding.evidence_coverage if self.grounding else 1.0

    @property
    def citation_score(self) -> float:
        return self.grounding.citation_score if self.grounding else 1.0

    @property
    def grounding_score(self) -> float:
        return self.grounding.grounding_score if self.grounding else self.confidence_score

    @property
    def retrieval_score(self) -> float:
        return self.grounding.retrieval_score if self.grounding else self.confidence_score


class AnswerGeneratorService:
    def __init__(
        self,
        llm_service: LLMService,
        citation_validator: CitationValidatorService | None = None,
        claim_verifier: ClaimVerificationService | None = None,
    ):
        self._llm = llm_service
        self._citation_validator = citation_validator or CitationValidatorService()
        self._claim_verifier = claim_verifier or ClaimVerificationService(llm_service)

    def generate(
        self,
        question: str,
        context_chunks: list[DocumentChunk],
        citation_chunks: list[DocumentChunk],
        history: list[dict],
        intent: str,
        response_length: str,
        best_relevance_score: float = 1.0,
        answer_style: str | None = None,
        full_document_chunks: list[DocumentChunk] | None = None,
    ) -> GeneratedAnswer:
        """`context_chunks` is everything the model is actually shown
        (post context-management: deduped, merged, ordered, compressed —
        may include neighbor chunks pulled in purely for surrounding
        context). `citation_chunks` is the narrower set citations are
        built from — the originally *matched* chunks, not their
        neighbors (a neighbor included only for context was never a
        "source" in its own right; this mirrors the same decision made
        for citations back in Phase 2). Citation *validation* still
        checks the model's inline markers against `context_chunks`
        (the full set it saw), since the model legitimately might cite
        a neighbor page it was shown — that's not a hallucination.

        `best_relevance_score` (the top retrieved/reranked score, 0..1
        ish) is one input to confidence_score — a strong top match with
        clean citations should read as higher-confidence than a weak
        match that also mis-cited something.

        `answer_style`: pass the value already computed by Phase 6's
        `QueryUnderstandingService` (result.plan.answer_style) to avoid
        classifying it twice; if omitted (e.g. a caller without query
        understanding wired in, or existing tests), it's classified here
        exactly as it always was.

        `full_document_chunks`: the whole document's chunks (not just
        what was retrieved for this question) — optional, enables the
        grounding pass's secondary-evidence-retrieval rescue when the
        retriever picked the wrong chunk for a given claim even though
        the document does contain the answer elsewhere (spec item 13)."""
        if answer_style is None:
            answer_style = classify_answer_style(question)
        messages = self._build_messages(question, context_chunks, history, intent, response_length, answer_style)

        reply = self._llm.complete(messages)

        return self._package_response(
            reply, context_chunks, citation_chunks, best_relevance_score, full_document_chunks
        )

    def _build_messages(
        self,
        question: str,
        context_chunks: list[DocumentChunk],
        history: list[dict],
        intent: str,
        response_length: str,
        answer_style: str,
    ) -> list[dict]:
        style_instruction = STYLE_INSTRUCTIONS.get(answer_style)
        system_prompt = prompts.build_rag_system_prompt(
            context_chunks, intent, response_length, answer_style_instruction=style_instruction
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": question})
        return messages

    def _package_response(
        self,
        reply: str,
        context_chunks: list[DocumentChunk],
        citation_chunks: list[DocumentChunk],
        best_relevance_score: float,
        full_document_chunks: list[DocumentChunk] | None = None,
    ) -> GeneratedAnswer:
        citations = build_citations(citation_chunks, limit=MAX_CITATIONS)
        used_chunks = [c.id for c in context_chunks]

        # Legacy confidence_score: unchanged computation, still based on
        # retrieval quality + whether the model's own inline citation
        # markers exist in the context it was given (spec item 7 — kept
        # separate from the new claim-level grounding metrics below).
        validation = self._citation_validator.validate(reply, context_chunks)
        confidence_score = max(0.0, min(1.0, best_relevance_score - validation.confidence_penalty))

        # Claim -> Evidence -> Citation grounding pass (spec items 3-9):
        # every factual/numeric/date sentence in `reply` is checked
        # against `context_chunks` ONLY (never chat history, never
        # outside knowledge — spec item 26), and anything that fails
        # verification is removed or the whole answer is replaced with
        # a "not found" fallback, never left in place unverified.
        grounding = self._claim_verifier.verify_and_repair(
            draft_answer=reply,
            context_chunks=context_chunks,
            retrieval_score=best_relevance_score,
            full_document_chunks=full_document_chunks,
        )

        return GeneratedAnswer(
            answer=grounding.grounded_answer,
            citations=citations,
            used_chunks=used_chunks,
            confidence_score=confidence_score,
            grounding=grounding,
        )

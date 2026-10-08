"""The 'answer a question' use case. This absorbs what used to be
directly inside routers/messages.py: summary-request detection,
page/chapter scoping for summaries, response-length inference, and
building/sending the final prompt. The router (api/routers/messages.py)
is now a thin adapter that just calls `QAService.answer()`.

Phase 2 Part 2: `answer()` now returns an `AnswerResult` (reply +
citations) instead of a bare string, so every response carries the exact
user-visible page(s) it was drawn from — see domain/citations.py for the
display-page priority rule (printed label, falling back to physical page
index; never blank).

Phase 7: page/chapter-scoped requests are no longer handled by an
ad-hoc regex branch here — `LongContextAnalyzer` classifies the question
(page range / section / chapter / multi-chapter / whole document /
ordinary), and `_answer_long_context` handles all of those uniformly via
`ChapterRetriever`/`PageRangeRetriever`/`SectionRetriever` (retrieve the
WHOLE scope, not top-k) and `LongContextSummarizer` (section-aware
map-reduce with recursive merging). This is what makes "explain chapter
3" — not just "summarize chapter 3" — get full-chapter treatment instead
of falling through to ordinary top-k RAG.
"""

import re
from dataclasses import dataclass

from ..config import settings
from ..context.context_manager import ContextManagerService
from ..domain.citations import Citation, build_citations
from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService, MessageRepository
from ..longcontext.cache import LongContextCache
from ..longcontext.chapter_outline_generator import ChapterOutlineGenerator
from ..longcontext.chapter_retriever import ChapterRetriever, SectionRetriever
from ..longcontext.long_context_analyzer import LongContextAnalyzer
from ..longcontext.map_reduce_summarizer import LongContextSummarizer
from ..longcontext.models import LongContextPlan, LongContextQueryType
from ..longcontext.page_range_retriever import PageRangeRetriever
from ..longcontext.study_guide_generator import StudyGuideGenerator
from ..retrieval.query_understanding import infer_response_length
from ..retrieval.retriever import Retriever
from . import prompts
from .answer_generator_service import AnswerGeneratorService
from .claim_verification_service import ClaimVerificationService, GroundingReport
from .claim_verification_service import NOT_FOUND_MESSAGE_AR, NOT_FOUND_MESSAGE_EN
from .summarization_service import SummarizationService

# Citations are meant to orient the reader, not enumerate every chunk
# touched — cap even a whole-document summary's citation list so the
# response stays a scannable list of source locations rather than a
# near-duplicate of the document's table of contents.
MAX_CITATIONS = 12

HISTORY_WINDOW = 6

_OUTLINE_REQUEST_RE = re.compile(
    r"\b(outline|table of contents|toc|list (the )?headings|structure of|فهرس|محتويات|هيكل)\b", re.IGNORECASE
)


@dataclass
class AnswerResult:
    reply: str
    citations: list[Citation]
    used_chunks: list[int | str | None]
    confidence_score: float
    grounding: GroundingReport | None = None

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


class QAService:
    def __init__(
        self,
        llm_service: LLMService,
        retriever: Retriever,
        summarization_service: SummarizationService,
        message_repo: MessageRepository,
        context_manager: ContextManagerService,
        answer_generator: AnswerGeneratorService,
        long_context_analyzer: LongContextAnalyzer,
        long_context_summarizer: LongContextSummarizer,
        long_context_cache: LongContextCache,
        study_guide_generator: StudyGuideGenerator,
        claim_verifier: ClaimVerificationService | None = None,
    ):
        self._llm = llm_service
        self._retriever = retriever
        self._summarizer = summarization_service
        self._messages = message_repo
        self._context_manager = context_manager
        self._answer_generator = answer_generator
        self._long_context_analyzer = long_context_analyzer
        self._long_context_summarizer = long_context_summarizer
        self._long_context_cache = long_context_cache
        self._study_guide_generator = study_guide_generator
        self._chapter_retriever = ChapterRetriever()
        self._section_retriever = SectionRetriever()
        self._page_range_retriever = PageRangeRetriever()
        self._outline_generator = ChapterOutlineGenerator()
        # Same grounding stage AnswerGeneratorService uses for ordinary
        # RAG answers, applied here too (spec item 12: the long-context
        # path must get the SAME grounding protection, not a bypass).
        self._claim_verifier = claim_verifier or ClaimVerificationService(llm_service)

    def answer(self, chat_id: int, question: str, all_chunks: list[DocumentChunk], chat) -> AnswerResult:
        """chat is the ORM Chat object — used to read/write `overview`.
        Kept as a loosely-typed parameter deliberately rather than
        widening ChatRepository's interface just for this one field;
        worth revisiting if more chat-level state accumulates here."""
        history = self._messages.get_recent(chat_id, HISTORY_WINDOW)
        self._messages.add(chat_id, "user", question)

        plan = self._long_context_analyzer.analyze(question)
        if plan.is_long_context:
            reply, citations, used_chunks, confidence, grounding = self._answer_long_context(
                chat_id, question, plan, all_chunks
            )
        else:
            reply, citations, used_chunks, confidence, grounding = self._answer_question(
                chat_id, question, all_chunks, history, chat
            )

        self._messages.add(chat_id, "assistant", reply)
        return AnswerResult(
            reply=reply, citations=citations, used_chunks=used_chunks, confidence_score=confidence, grounding=grounding
        )

    # ---- Phase 7: long-context (chapter/section/page-range/document) ----

    def _answer_long_context(
        self, chat_id: int, question: str, plan: LongContextPlan, all_chunks: list[DocumentChunk]
    ) -> tuple[str, list[Citation], list, float, GroundingReport | None]:
        scope_chunks, focus, confidence, not_found_message = self._resolve_scope(plan, all_chunks)

        if not scope_chunks:
            # Fail-closed (spec item 13): a requested chapter/section/
            # multi-chapter scope that genuinely wasn't found returns a
            # clear "not found" reply instead of silently answering from
            # the whole document under that scope's name.
            return not_found_message or "I couldn't find that in this document.", [], [], 0.0, None

        if _OUTLINE_REQUEST_RE.search(question) and plan.query_type != LongContextQueryType.PAGE_RANGE:
            # Free, instant, no LLM call — see chapter_outline_generator.py.
            # Deterministically built straight from chunk headings, so it
            # doesn't go through the grounding pass (nothing an LLM could
            # have hallucinated here).
            outline = self._outline_generator.generate(scope_chunks)
            reply = self._outline_generator.render_markdown(outline)
            citations = build_citations(scope_chunks, limit=MAX_CITATIONS)
            return reply, citations, [c.id for c in scope_chunks], confidence, None

        cache_key = (plan.query_type.value, tuple(plan.chapters), plan.page_range, plan.section_hint, plan.explanation_mode)
        cached = self._long_context_cache.get(chat_id, cache_key, scope_chunks)
        grounding: GroundingReport | None = None
        if cached is not None:
            # Cached replies were already grounded before being cached
            # (see below) — no need to re-verify.
            reply = cached
        else:
            draft = self._long_context_summarizer.explain_scope(
                scope_chunks,
                question=question,
                focus=focus,
                explanation_mode=plan.explanation_mode,
                response_length=plan.response_length,
            )
            # Long-context answers get the SAME grounding protection as
            # ordinary RAG answers (spec item 12) — verified against
            # exactly the chunks in this scope, nothing else.
            grounding = self._claim_verifier.verify_and_repair(
                draft_answer=draft,
                context_chunks=scope_chunks,
                retrieval_score=confidence,
                full_document_chunks=all_chunks,
            )
            reply = grounding.grounded_answer
            self._long_context_cache.set(chat_id, cache_key, scope_chunks, reply)

        if plan.explanation_mode in ("study_notes", "exam_prep"):
            reply = self._append_study_guide_highlights(reply, scope_chunks, focus)

        citations = build_citations(scope_chunks, limit=MAX_CITATIONS)
        used_chunks = [c.id for c in scope_chunks]
        return reply, citations, used_chunks, confidence, grounding

    def _resolve_scope(
        self, plan: LongContextPlan, all_chunks: list[DocumentChunk]
    ) -> tuple[list[DocumentChunk], str, float, str | None]:
        """Returns (scope_chunks, focus_description, confidence,
        not_found_message). Spec item 13 (fail-closed scope fallback): a
        requested scope that wasn't actually found (e.g. a chapter number
        that doesn't match any chunk's metadata) now returns an EMPTY
        scope with a clear not-found message, instead of silently
        falling back to the whole document and pretending that's the
        requested chapter/section. Partial multi-chapter matches (one of
        two found) are the one case that still combines real, actually-
        matched content rather than unrelated material — that's not a
        guess, it's just incomplete."""
        if plan.query_type == LongContextQueryType.PAGE_RANGE and plan.page_range:
            start, end = plan.page_range
            chunks = self._page_range_retriever.retrieve_range(start, end, all_chunks)
            focus = f"pages {start}-{end}" if start != end else f"page {start}"
            if chunks:
                return chunks, focus, 1.0, None
            return [], focus, 0.0, f"I couldn't find {focus} in this document."

        if plan.query_type == LongContextQueryType.CHAPTER_QUERY and plan.chapters:
            chapter_ref = plan.chapters[0]
            chunks = self._chapter_retriever.retrieve_chapter(chapter_ref, all_chunks)
            if chunks:
                return chunks, f"Chapter {chapter_ref}", 1.0, None
            return [], f"Chapter {chapter_ref}", 0.0, f"I couldn't find Chapter {chapter_ref} in this document."

        if plan.query_type == LongContextQueryType.MULTI_CHAPTER_QUERY and len(plan.chapters) == 2:
            by_chapter = self._chapter_retriever.retrieve_multi(plan.chapters, all_chunks)
            found = [ref for ref in plan.chapters if by_chapter.get(ref)]
            combined = [c for ref in plan.chapters for c in by_chapter.get(ref, [])]
            focus = f"chapter {plan.chapters[0]} and chapter {plan.chapters[1]}"
            if len(found) == 2:
                return combined, focus, 1.0, None
            if combined:
                # Genuinely-found partial content, not a guess — kept as
                # a (lower-confidence) partial answer rather than failing
                # closed entirely, since real matched material exists.
                return combined, f"{focus} (only chapter {found[0]} was found)", 0.5, None
            return [], focus, 0.0, f"I couldn't find {focus} in this document."

        if plan.query_type == LongContextQueryType.SECTION_QUERY and plan.section_hint:
            chunks = self._section_retriever.retrieve_section(plan.section_hint, all_chunks)
            if chunks:
                return chunks, f'the section on "{plan.section_hint}"', 1.0, None
            return (
                [],
                f'the section on "{plan.section_hint}"',
                0.0,
                f"I couldn't find a section on \"{plan.section_hint}\" in this document.",
            )

        # DOCUMENT_QUERY, or a long-scope hint with nothing more specific
        # resolved: no specific scope was actually *requested*, so using
        # the whole document here isn't a fallback-from-failure — it's
        # the correctly-resolved scope.
        return all_chunks, "the document", 1.0, None

    def _append_study_guide_highlights(self, reply: str, scope_chunks: list[DocumentChunk], focus: str) -> str:
        """Adds a short, focused slice of study-guide content (key
        concepts + a couple of likely exam questions) rather than the
        full StudyGuide — keeps the reply readable instead of dumping
        every generated field into one wall of text. The full structured
        StudyGuide is available via StudyGuideGenerator directly for any
        future dedicated endpoint that wants it in full.

        Key concepts are short LLM-generated factual phrases, so they go
        through the SAME grounding pass as the main answer before being
        appended (spec item 18: no answer-generation route — including
        this one — may bypass semantic grounding). Exam questions are
        left as-is: a question is a prompt for the reader, not a sourced
        factual assertion, so claim verification doesn't apply to it."""
        guide = self._study_guide_generator.generate(scope_chunks, focus)
        if not guide.key_concepts and not guide.exam_questions:
            return reply

        extra = []
        if guide.key_concepts:
            concepts_draft = "\n".join(guide.key_concepts[:8])
            concepts_report = self._claim_verifier.verify_and_repair(
                concepts_draft, context_chunks=scope_chunks, retrieval_score=1.0, full_document_chunks=scope_chunks
            )
            not_found = concepts_report.grounded_answer.strip() in (NOT_FOUND_MESSAGE_EN, NOT_FOUND_MESSAGE_AR)
            grounded_concepts = [] if not_found else [ln for ln in concepts_report.grounded_answer.split("\n") if ln.strip()]
            if grounded_concepts:
                extra.append("**Key concepts:** " + ", ".join(grounded_concepts))
        if guide.exam_questions:
            questions = "\n".join(f"- {q}" for q in guide.exam_questions[:5])
            extra.append(f"**Possible exam questions:**\n{questions}")

        if not extra:
            return reply
        return reply + "\n\n" + "\n\n".join(extra)

    # ---- ordinary top-k RAG (Phase 1-6, unchanged) ----

    def _answer_question(
        self, chat_id: int, question: str, all_chunks: list[DocumentChunk], history: list[dict], chat
    ) -> tuple[str, list[Citation], list, float, GroundingReport | None]:
        result = self._retriever.retrieve(chat_id, question, all_chunks, history)

        if result.is_out_of_scope:
            overview = chat.overview
            if not overview:
                overview = self._summarizer.generate_overview(all_chunks)
                chat.overview = overview
            reply = self._summarizer.generate_out_of_scope_reply(question, overview)
            return reply, [], [], 0.0, None

        response_length = infer_response_length(question, result.intent)

        # Context management (Phase 5): dedup, merge adjacent related
        # chunks, order by section/chapter/page/relevance, and compress
        # to the configured token budget — all BEFORE the prompt is
        # built, so prompts.py keeps receiving the same
        # `list[DocumentChunk]` shape it always has.
        #
        # `result.plan` is Phase 6's QueryAnalysis, already computed once
        # inside Retriever (via QueryUnderstandingService) — reused here
        # rather than recomputed, since it's structurally compatible with
        # what ContextManagerService.prepare() needs (same keywords/
        # numbers field names retrieval-layer code already relied on).
        prepared = self._context_manager.prepare(
            chunks=result.chunks,
            relevance_by_id=result.relevance_by_id or {},
            token_budget=settings.context_token_budget,
            analysis=result.plan,
        )

        best_relevance = max((result.relevance_by_id or {}).values(), default=1.0)
        generated = self._answer_generator.generate(
            question=question,
            context_chunks=prepared.chunks,
            citation_chunks=result.matched_chunks,
            history=history,
            intent=result.intent,
            response_length=response_length,
            best_relevance_score=min(best_relevance, 1.0),
            answer_style=result.plan.answer_style if result.plan else None,
            full_document_chunks=all_chunks,
        )
        return (
            generated.answer,
            generated.citations,
            generated.used_chunks,
            generated.confidence_score,
            generated.grounding,
        )

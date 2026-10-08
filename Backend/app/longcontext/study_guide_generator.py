"""StudyGuideGenerator (spec item 8). One structured-JSON LLM call
rather than six separate ones (key concepts, definitions, formulas,
FAQs, exam questions, flashcards each as their own call) — cheaper and
faster, and lets the model see the full material once rather than
fragmenting its view of the chapter across unrelated calls. For a scope
too large to fit in one call, the material is first condensed via
`LongContextSummarizer.explain_scope` (mode='detailed', so nothing
important gets lost in the condensation) and the study guide is
generated from that condensed text instead of the raw chunks.
"""

import json
from dataclasses import dataclass, field

from ..application import prompts
from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService
from .map_reduce_summarizer import MAP_REDUCE_CHAR_THRESHOLD, LongContextSummarizer


@dataclass
class Definition:
    term: str
    definition: str


@dataclass
class FAQ:
    question: str
    answer: str


@dataclass
class Flashcard:
    front: str
    back: str


@dataclass
class StudyGuide:
    key_concepts: list[str] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    faqs: list[FAQ] = field(default_factory=list)
    exam_questions: list[str] = field(default_factory=list)
    flashcards: list[Flashcard] = field(default_factory=list)


class StudyGuideGenerator:
    def __init__(self, llm_service: LLMService, summarizer: LongContextSummarizer | None = None):
        self._llm = llm_service
        self._summarizer = summarizer or LongContextSummarizer(llm_service)

    def generate(self, chunks: list[DocumentChunk], focus: str) -> StudyGuide:
        if not chunks:
            return StudyGuide()

        material_text = self._material_text(chunks, focus)

        try:
            raw = self._llm.complete(
                [
                    {"role": "system", "content": prompts.build_study_guide_prompt(focus)},
                    {"role": "user", "content": material_text},
                ],
                temperature=0,
            )
            return self._parse(raw)
        except Exception:
            # A malformed/failed generation should degrade to an empty
            # (but valid) StudyGuide rather than break the whole request
            # — this is a "nice to have" output, not the primary answer.
            return StudyGuide()

    def _material_text(self, chunks: list[DocumentChunk], focus: str) -> str:
        total_chars = sum(len(c.text) for c in chunks)
        if total_chars <= MAP_REDUCE_CHAR_THRESHOLD:
            return "\n\n---\n\n".join(f"{prompts.excerpt_header(c)}\n{c.text}" for c in chunks)

        # Too large for one call — condense first via the same
        # map-reduce machinery used for long-context explanations,
        # requesting a detailed (not lossy) condensation so study-guide
        # generation still has enough material to draw from.
        return self._summarizer.explain_scope(
            chunks,
            question=f"Cover everything notable in {focus} in detail for study guide extraction.",
            focus=focus,
            explanation_mode="detailed",
            response_length="long",
        )

    @staticmethod
    def _parse(raw: str) -> StudyGuide:
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)

        return StudyGuide(
            key_concepts=list(data.get("key_concepts", []))[:15],
            definitions=[Definition(**d) for d in data.get("definitions", []) if "term" in d and "definition" in d][:15],
            formulas=list(data.get("formulas", []))[:15],
            faqs=[FAQ(**f) for f in data.get("faqs", []) if "question" in f and "answer" in f][:15],
            exam_questions=list(data.get("exam_questions", []))[:15],
            flashcards=[Flashcard(**c) for c in data.get("flashcards", []) if "front" in c and "back" in c][:15],
        )

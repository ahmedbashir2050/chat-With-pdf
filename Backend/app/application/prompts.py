"""Prompt construction. Same wording/instructions as the original
messages.py and summarization.py — moved here so prompt engineering is a
one-place concern, separate from retrieval orchestration and HTTP
handling. Nothing about the actual prompt text changed in this phase.
"""

from ..domain.entities import DocumentChunk

RAG_LENGTH_INSTRUCTIONS = {
    "short": "Answer in 1-3 concise sentences. Do not add extra detail beyond what's asked.",
    "long": "Answer thoroughly — use multiple paragraphs, cover relevant nuance, and don't skip steps in the reasoning.",
    "auto": "Match your answer's length to the question: brief (1-3 sentences) for simple factual questions, fuller and more organized for complex, conceptual, or open-ended ones.",
}

SUMMARY_LENGTH_INSTRUCTIONS = {
    "short": "Keep it tight: a handful of bullet points covering only the most important ideas. Do not elaborate.",
    "long": "Be thorough and comprehensive: use headings and bullet points, cover every major section, and don't skip nuance.",
    "auto": "Use your judgment on length: enough to cover the material well, organized clearly, without padding.",
}

# Shared framing so a summary reads like a professional briefing (opening
# orientation sentence, then organized sections) rather than a flat,
# undifferentiated bullet dump.
BRIEFING_STYLE = (
    "Write like a clear, well-organized briefing, not a flat list of trivia:\n"
    "- Open with one sentence orienting the reader to what this covers and why "
    "it matters, before diving into specifics.\n"
    "- Group related points under short topic headings (not just one long "
    "bullet list) when the material has more than one distinct theme.\n"
    "- Explain WHY something matters where that's evident from the text, not "
    "just WHAT it says — connect ideas rather than listing disconnected facts.\n"
    "- Define any technical term the first time it's used, briefly, in plain "
    "language."
)


def excerpt_header(c: DocumentChunk) -> str:
    """[Page X] when the chunk has no hierarchy context (unchanged from
    Phase 1); [Page X — Chapter Y > Section Z] when it does. Giving the
    model this breadcrumb — rather than just a page number — is what lets
    it say "in the Methods section" instead of just "on page 12", and
    lets it judge two same-topic excerpts from different chapters as
    contextually distinct instead of interchangeable.

    X is always `c.physical_page` — the 1-based physical PDF page index,
    and the ONLY page identity ever shown to the model. There is no
    printed-page-label alternative here: a document's own front-matter
    roman numerals or a restarted printed page number are never surfaced
    to the model as something it could cite instead."""
    breadcrumb_parts = [p for p in (c.chapter, c.section, c.subsection, c.heading) if p]
    if not breadcrumb_parts:
        return f"[Page {c.physical_page}]"
    breadcrumb = " > ".join(dict.fromkeys(breadcrumb_parts))  # dedupe while preserving order
    return f"[Page {c.physical_page} — {breadcrumb}]"


def _excerpt_block(chunks: list[DocumentChunk]) -> str:
    return "\n\n---\n\n".join(f"{excerpt_header(c)}\n{c.text}" for c in chunks)


def build_rag_system_prompt(
    chunks: list[DocumentChunk], intent: str, response_length: str, answer_style_instruction: str | None = None
) -> str:
    context_text = _excerpt_block(chunks)
    length_instruction = RAG_LENGTH_INSTRUCTIONS.get(response_length, RAG_LENGTH_INSTRUCTIONS["auto"])

    teaching_instruction = (
        "Explain this the way a good teacher would: define any key terms before "
        "using them, connect the idea to the bigger picture of what the document "
        "is about, and — if it genuinely helps understanding — walk through a "
        "brief concrete example drawn from the text. Break the explanation into "
        "short paragraphs or bullet points rather than one dense block."
        if intent == "explain"
        else "Answer directly and clearly. If the answer naturally has a few "
        "distinct parts, present them as short bullet points rather than one "
        "run-on sentence."
    )

    style_line = f"\n7. {answer_style_instruction}" if answer_style_instruction else ""

    return (
        "You are a knowledgeable, patient teacher helping a student understand "
        "this specific document. Rules:\n"
        "1. Use ONLY the excerpts below — never outside knowledge, even if you "
        "happen to know the answer some other way.\n"
        "2. If the excerpts don't contain the answer, say so plainly: "
        '"I couldn\'t find that in this document." Do not guess or improvise.\n'
        f"3. {teaching_instruction}\n"
        "4. End every factual sentence with the page it came from, like [p. X], "
        "where X is EXACTLY the number shown after \"Page\" in that excerpt's "
        "header — always a plain physical page number. Copy it exactly; never "
        "convert, renumber, or recalculate it, and never substitute a different "
        "page-numbering scheme (a printed page number, a chapter-relative number, "
        "a roman numeral) even if the document's own text mentions one — only the "
        "number in the excerpt header is ever a valid citation. "
        "If a point draws on multiple pages, cite all of them.\n"
        f"5. {length_instruction}\n"
        "6. Respond in the SAME language the student's question is written in "
        "(e.g. answer in Arabic if asked in Arabic), regardless of what "
        f"language the source document itself is written in.{style_line}\n\n"
        f"--- EXCERPTS FROM THE DOCUMENT ---\n{context_text}"
    )


def build_summary_single_shot_prompt(
    chunks: list[DocumentChunk], focus: str, length_instruction: str, mode_instruction: str | None = None
) -> str:
    full_text = _excerpt_block(chunks)
    mode_line = f"\n6. {mode_instruction}" if mode_instruction else ""
    return (
        f"Summarize {focus} below for a student trying to actually "
        "understand it, not just skim it. Rules:\n"
        "1. Use ONLY the text provided — no outside knowledge.\n"
        f"2. {BRIEFING_STYLE}\n"
        "3. After each point, cite the page(s) exactly as the number shown in "
        "the excerpt headers, like [p. X] — always a plain physical page "
        "number. Never convert, renumber, or substitute a different "
        "page-numbering scheme, even if the source text mentions one.\n"
        f"4. {length_instruction}\n"
        "5. Respond in the SAME language as the student's request below, "
        f"regardless of what language the source text itself is in.{mode_line}\n\n"
        f"--- SOURCE START ---\n{full_text}\n--- SOURCE END ---"
    )


def build_summary_batch_prompt(mode_instruction: str | None = None) -> str:
    mode_line = f" {mode_instruction}" if mode_instruction else ""
    return (
        "Summarize the following excerpt in concise bullet points, "
        "grouped under a short topic heading if it covers more than "
        "one theme. Cite the page for each point like [p. X]. Do "
        f"not add information that isn't in the excerpt.{mode_line}"
    )


def build_summary_merge_prompt(focus: str, length_instruction: str, mode_instruction: str | None = None) -> str:
    mode_line = f" {mode_instruction}" if mode_instruction else ""
    return (
        f"Merge these partial summaries of {focus} into one cohesive, "
        f"well-organized briefing. {BRIEFING_STYLE} Keep the [p. X] "
        "citations. Do not invent new information beyond what's in the "
        f"partial summaries. {length_instruction} Respond in the SAME "
        f"language as the student's original request below.{mode_line}"
    )


def build_overview_prompt() -> str:
    return (
        "Based on these excerpts sampled across a document, list the 4-7 "
        "main topics or sections it covers, as a short bullet list a reader "
        "could use to know what they can ask about. Each bullet: a few words "
        "only, not a full sentence, no page citations. This is a "
        "table-of-contents-style index, not a summary — do not explain each "
        "topic in depth."
    )


def build_study_guide_prompt(focus: str) -> str:
    return (
        f"From the material about {focus} below, extract study guide content. "
        "Respond with ONLY a JSON object (no commentary, no markdown fences) with these keys:\n"
        '"key_concepts": array of short strings (concept names),\n'
        '"definitions": array of {"term": str, "definition": str} objects,\n'
        '"formulas": array of short strings describing each formula/equation found (empty array if none),\n'
        '"faqs": array of {"question": str, "answer": str} objects — questions a student would likely ask,\n'
        '"exam_questions": array of short strings — questions phrased the way an exam might ask them,\n'
        '"flashcards": array of {"front": str, "back": str} objects.\n'
        "Use ONLY the provided material — no outside knowledge. Every definition/answer should be "
        "phrased so it stands alone without needing to see the source. Respond in the SAME language "
        "as the material below. Keep each array to a reasonable, non-exhaustive length (roughly 5-10 items)."
    )


def build_out_of_scope_prompt() -> str:
    return (
        "The student just asked something this document does not appear "
        "to cover. Kindly let them know that in one sentence, without being "
        "blunt about it, then present the topics below as friendly "
        "suggestions of what they could ask about instead — a short bullet "
        "list is fine. Keep the whole reply brief. Respond in the SAME "
        "language as the student's question."
    )

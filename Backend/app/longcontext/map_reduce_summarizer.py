"""LongContextSummarizer (spec items 4, 5, 11). Builds on
`SummarizationService`'s existing single-shot/map-reduce logic
(unchanged, still used as-is for the old summary-only path) rather than
reimplementing LLM plumbing — the additions here are specifically what
Phase 7 needs beyond what already existed:

- Section-aware MAP batching: chunks are grouped by (chapter, section)
  before batching, so one MAP call summarizes one coherent section
  rather than an arbitrary fixed-size window of chunks that might cut
  a section in half. Falls back to fixed-size batching for chunks
  without section metadata (pre-Phase-2 documents).
- Recursive REDUCE: `SummarizationService._summarize_map_reduce` merges
  all partial summaries in a single LLM call — fine for a normal
  chapter (a handful of sections), but a very large chapter or a whole
  document could produce more section summaries than fit in one merge
  prompt. This recurses: batch the summaries themselves, reduce each
  batch, repeat until what's left fits in one merge call.
- `explain_scope`: the same single-shot/map-reduce choice as
  `SummarizationService.summarize`, but parameterized by an explanation
  *mode* (simple/detailed/academic/teaching/exam_prep/study_notes/
  bullet_points) rather than always producing a "summary" — this is
  what makes "explain chapter 3" and "summarize chapter 3" both route
  through the same machinery with different prompt instructions.
"""

from ..context.answer_style import STYLE_INSTRUCTIONS
from ..context.token_utils import estimate_total_tokens
from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService
from ..application import prompts

# Above this, a single merge call risks exceeding the model's context
# window if section summaries are long — recurse instead of hoping it
# fits. Deliberately conservative (same spirit as context/token_utils.py
# and config.context_token_budget) rather than tuned against a specific
# model's exact limit.
MAX_SUMMARIES_PER_REDUCE = 8
MAP_REDUCE_CHAR_THRESHOLD = 300_000  # same threshold SummarizationService already uses for single-shot vs map-reduce


def _group_by_section(chunks: list[DocumentChunk]) -> list[list[DocumentChunk]]:
    """Groups consecutive chunks (in the order given — callers pass
    already page-ordered chunks) that share the same (chapter, section)
    into one batch. Chunks without section metadata each become their
    own single-chunk group, which naturally falls back to something
    close to the old fixed-size behavior when metadata is absent."""
    groups: list[list[DocumentChunk]] = []
    current_key = None
    current_group: list[DocumentChunk] = []

    for c in chunks:
        key = (c.chapter, c.section) if c.section else None
        if key is not None and key == current_key:
            current_group.append(c)
        else:
            if current_group:
                groups.append(current_group)
            current_group = [c]
            current_key = key

    if current_group:
        groups.append(current_group)

    return groups


def _split_oversized_groups(groups: list[list[DocumentChunk]], max_chunks: int = 10) -> list[list[DocumentChunk]]:
    """A single section can still be too large for one MAP call (a very
    long chapter section) — split it further into fixed-size sub-batches
    rather than sending an unbounded prompt."""
    result = []
    for group in groups:
        for i in range(0, len(group), max_chunks):
            result.append(group[i : i + max_chunks])
    return result


class LongContextSummarizer:
    def __init__(self, llm_service: LLMService):
        self._llm = llm_service

    def explain_scope(
        self, chunks: list[DocumentChunk], question: str, focus: str, explanation_mode: str, response_length: str
    ) -> str:
        if not chunks:
            return "I couldn't find that section in this document."

        mode_instruction = STYLE_INSTRUCTIONS.get(explanation_mode)
        length_instruction = prompts.SUMMARY_LENGTH_INSTRUCTIONS.get(
            response_length, prompts.SUMMARY_LENGTH_INSTRUCTIONS["auto"]
        )

        total_chars = sum(len(c.text) for c in chunks)
        if total_chars <= MAP_REDUCE_CHAR_THRESHOLD:
            return self._single_shot(chunks, question, focus, length_instruction, mode_instruction)
        return self._map_reduce(chunks, question, focus, length_instruction, mode_instruction)

    def _single_shot(
        self, chunks: list[DocumentChunk], question: str, focus: str, length_instruction: str, mode_instruction: str | None
    ) -> str:
        system_content = prompts.build_summary_single_shot_prompt(chunks, focus, length_instruction, mode_instruction)
        return self._llm.complete(
            [{"role": "system", "content": system_content}, {"role": "user", "content": question}]
        )

    def _map_reduce(
        self, chunks: list[DocumentChunk], question: str, focus: str, length_instruction: str, mode_instruction: str | None
    ) -> str:
        groups = _split_oversized_groups(_group_by_section(chunks))
        partials = [self._map_one_batch(batch, mode_instruction) for batch in groups]
        final_batch = self._reduce_to_small_batch(partials, focus, length_instruction, mode_instruction)
        return self._final_pass(final_batch, question, focus, length_instruction, mode_instruction)

    def _map_one_batch(self, batch: list[DocumentChunk], mode_instruction: str | None) -> str:
        batch_text = "\n\n---\n\n".join(f"{prompts.excerpt_header(c)}\n{c.text}" for c in batch)
        return self._llm.complete(
            [
                {"role": "system", "content": prompts.build_summary_batch_prompt(mode_instruction)},
                {"role": "user", "content": batch_text},
            ]
        )

    def _reduce_to_small_batch(
        self, partials: list[str], focus: str, length_instruction: str, mode_instruction: str | None
    ) -> list[str]:
        """Recursively merges partial summaries down to at most
        MAX_SUMMARIES_PER_REDUCE (spec item 11's "repeat until it fits")
        — but deliberately stops there rather than reducing all the way
        to one, so `_final_pass` can do the single LLM call that both
        finishes the reduction AND addresses the user's actual question,
        instead of one merge call to combine everything and a second,
        redundant one to answer the question on top of that."""
        current = partials
        while len(current) > MAX_SUMMARIES_PER_REDUCE:
            next_level = []
            for i in range(0, len(current), MAX_SUMMARIES_PER_REDUCE):
                batch = current[i : i + MAX_SUMMARIES_PER_REDUCE]
                next_level.append(self._merge_batch(batch, focus, length_instruction, mode_instruction))
            current = next_level
        return current

    def _merge_batch(
        self, summaries: list[str], focus: str, length_instruction: str, mode_instruction: str | None
    ) -> str:
        combined = "\n\n".join(f"Section {i + 1} summary:\n{s}" for i, s in enumerate(summaries))
        return self._llm.complete(
            [
                {
                    "role": "system",
                    "content": prompts.build_summary_merge_prompt(focus, length_instruction, mode_instruction),
                },
                {"role": "user", "content": f"{combined}\n\n---\nOriginal request: (intermediate merge step)"},
            ]
        )

    def _final_pass(
        self, summaries: list[str], question: str, focus: str, length_instruction: str, mode_instruction: str | None
    ) -> str:
        """The single final merge call: combines the (small, post-
        reduction) set of partial summaries into one cohesive answer that
        directly addresses the user's original question/phrasing. When
        `explain_scope`'s MAP step produced exactly one partial (a small
        scope with just one section), this is also the only LLM call
        `_map_reduce` makes beyond that single MAP call."""
        if len(summaries) == 1:
            combined = summaries[0]
        else:
            combined = "\n\n".join(f"Section {i + 1} summary:\n{s}" for i, s in enumerate(summaries))
        return self._llm.complete(
            [
                {
                    "role": "system",
                    "content": prompts.build_summary_merge_prompt(focus, length_instruction, mode_instruction),
                },
                {"role": "user", "content": f"{combined}\n\n---\nOriginal request: {question}"},
            ]
        )

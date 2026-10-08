"""Summarization use cases. Same single-shot-vs-map-reduce logic as the
original summarization.py, restructured as a class depending on
LLMService (injected) instead of a module-level OpenAI client import.
"""

from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService
from . import prompts

MAX_CHARS_SINGLE_SHOT = 300_000  # ~75k tokens of source, fits gpt-4o-mini's window


class SummarizationService:
    def __init__(self, llm_service: LLMService):
        self._llm = llm_service

    def summarize(
        self, chunks: list[DocumentChunk], question: str, focus: str = "the document", response_length: str = "auto"
    ) -> str:
        if not chunks:
            return "I couldn't find that section in this document."

        length_instruction = prompts.SUMMARY_LENGTH_INSTRUCTIONS.get(
            response_length, prompts.SUMMARY_LENGTH_INSTRUCTIONS["auto"]
        )

        if self._estimate_chars(chunks) <= MAX_CHARS_SINGLE_SHOT:
            return self._summarize_whole(chunks, question, focus, length_instruction)
        return self._summarize_map_reduce(chunks, question, focus, length_instruction)

    def generate_overview(self, chunks: list[DocumentChunk]) -> str:
        """A short, scannable list of the main topics a document covers —
        NOT a summary. Generated once at upload time and cached on the
        chat; used to redirect out-of-scope questions toward what the
        document actually covers."""
        if not chunks:
            return ""

        sample = chunks if len(chunks) <= 40 else chunks[:: max(1, len(chunks) // 40)]
        sample_text = "\n\n---\n\n".join(f"{prompts.excerpt_header(c)}\n{c.text[:300]}" for c in sample)

        return self._llm.complete(
            [
                {"role": "system", "content": prompts.build_overview_prompt()},
                {"role": "user", "content": sample_text},
            ]
        )

    def generate_out_of_scope_reply(self, question: str, overview: str) -> str:
        return self._llm.complete(
            [
                {"role": "system", "content": prompts.build_out_of_scope_prompt()},
                {
                    "role": "user",
                    "content": f"Student's question: {question}\n\nWhat this document covers:\n{overview}",
                },
            ]
        )

    @staticmethod
    def _estimate_chars(chunks: list[DocumentChunk]) -> int:
        return sum(len(c.text) for c in chunks)

    def _summarize_whole(self, chunks: list[DocumentChunk], question: str, focus: str, length_instruction: str) -> str:
        system_content = prompts.build_summary_single_shot_prompt(chunks, focus, length_instruction)
        return self._llm.complete(
            [
                {"role": "system", "content": system_content},
                {"role": "user", "content": question},
            ]
        )

    def _summarize_map_reduce(
        self, chunks: list[DocumentChunk], question: str, focus: str, length_instruction: str
    ) -> str:
        batch_size = 6
        partials: list[str] = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_text = "\n\n---\n\n".join(f"{prompts.excerpt_header(c)}\n{c.text}" for c in batch)
            summary = self._llm.complete(
                [
                    {"role": "system", "content": prompts.build_summary_batch_prompt()},
                    {"role": "user", "content": batch_text},
                ]
            )
            partials.append(summary)

        if len(partials) == 1:
            return partials[0]

        combined = "\n\n".join(f"Section {i + 1} summary:\n{s}" for i, s in enumerate(partials))
        return self._llm.complete(
            [
                {"role": "system", "content": prompts.build_summary_merge_prompt(focus, length_instruction)},
                {"role": "user", "content": f"{combined}\n\n---\nOriginal request: {question}"},
            ]
        )

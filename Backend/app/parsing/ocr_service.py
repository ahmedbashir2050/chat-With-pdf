"""OCR implementation. Behavior unchanged from the original pdf_utils.py:
a page with no embedded text gets rasterized and transcribed via a
vision-capable chat model. Isolated into its own adapter (rather than
living inside the parser) specifically so a future local-OCR-first tier
(Phase 1 finding: the original spec wants embedded text → local OCR →
vision fallback, in that order, to minimize OpenAI usage) can be added
here without the parser needing to know or care.
"""

from ..domain.interfaces import LLMService

_TRANSCRIBE_PROMPT = (
    "Transcribe all text visible in this scanned document page exactly as "
    "written, preserving line breaks and reading order. Output ONLY the "
    "transcribed text, nothing else — no commentary."
)


class VisionOCRService:
    """Implements domain.interfaces.OCRService. Costs one LLM vision call
    per invocation — the parser only calls this when normal text
    extraction comes back empty for a page, never unconditionally."""

    def __init__(self, llm_service: LLMService):
        self._llm = llm_service

    def transcribe_page_image(self, image_png_bytes: bytes) -> str:
        return self._llm.complete_vision(_TRANSCRIBE_PROMPT, image_png_bytes)

"""PyMuPDF-based document parsing. Text extraction, page-label detection,
and chunking logic are unchanged from the original pdf_utils.py — this is
a structural move (module-level functions → a class implementing
domain.interfaces.DocumentParser, with OCR injected rather than imported
directly) not a behavior rewrite. Semantic/structural chunking (headings,
paragraphs, tables) is explicitly deferred to a later phase — see the
Phase 1 review, §3.2.
"""

import re

import fitz  # PyMuPDF

from ..domain.entities import DocumentChunk
from ..domain.interfaces import OCRService

# Traditional Arabic "Abjad" letter-numeral order — this is what many
# Arabic academic documents use to number front-matter pages before the
# main body restarts at "page 1", the same way Western documents use
# lowercase roman numerals (i, ii, iii...) for that purpose.
ABJAD_ORDER = [
    "أ", "ب", "ج", "د", "ه", "و", "ز", "ح", "ط", "ي",
    "ك", "ل", "م", "ن", "س", "ع", "ف", "ص", "ق", "ر",
    "ش", "ت", "ث", "خ", "ذ", "ض", "ظ", "غ",
]

_DIGIT_RE = re.compile(r"^[0-9\u0660-\u0669]{1,4}$")  # Latin or Arabic-Indic digits
_ROMAN_RE = re.compile(r"^[ivxlcdmIVXLCDM]{1,7}$")
_SINGLE_LETTER_RE = re.compile(r"^[a-zA-Z]$")


def _looks_like_page_label(token: str) -> bool:
    token = token.strip().strip(".-–—")
    if not token:
        return False
    if _DIGIT_RE.match(token):
        return True
    if _ROMAN_RE.match(token):
        return True
    if token in ABJAD_ORDER:
        return True
    if _SINGLE_LETTER_RE.match(token):
        return True
    return False


def _detect_page_label(page: "fitz.Page") -> str | None:
    """Looks for a short numeric/lettered token in the top/bottom ~10% of
    the page — where a printed page number conventionally sits — distinct
    from the PDF's own physical page index."""
    words = page.get_text("words")
    if not words:
        return None

    page_height = page.rect.height
    top_band = page_height * 0.10
    bottom_band = page_height * 0.90

    for w in words:
        y0 = w[1]
        text = w[4]
        if (y0 < top_band or y0 > bottom_band) and _looks_like_page_label(text):
            return text.strip()
    return None


class PyMuPDFDocumentParser:
    """Implements domain.interfaces.DocumentParser."""

    def __init__(self, ocr_service: OCRService):
        self._ocr = ocr_service

    def extract_chunks(self, pdf_bytes: bytes, chat_id: int, chunk_size: int = 800) -> list[DocumentChunk]:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        chunks: list[DocumentChunk] = []

        try:
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                if not text:
                    pix = page.get_pixmap(dpi=200)
                    text = self._ocr.transcribe_page_image(pix.tobytes("png")).strip()
                if not text:
                    continue

                label = _detect_page_label(page)
                chunks.extend(self._split_into_chunks(text, chat_id, i + 1, label, chunk_size))
        finally:
            doc.close()

        return chunks

    @staticmethod
    def _split_into_chunks(
        text: str, chat_id: int, page_number: int, label: str | None, chunk_size: int
    ) -> list[DocumentChunk]:
        words = text.split()
        buffer: list[str] = []
        length = 0
        out: list[DocumentChunk] = []

        for word in words:
            if length + len(word) + 1 > chunk_size:
                out.append(DocumentChunk(chat_id=chat_id, page=page_number, page_label=label, text=" ".join(buffer)))
                buffer = []
                length = 0
            buffer.append(word)
            length += len(word) + 1

        if buffer:
            out.append(DocumentChunk(chat_id=chat_id, page=page_number, page_label=label, text=" ".join(buffer)))

        return out

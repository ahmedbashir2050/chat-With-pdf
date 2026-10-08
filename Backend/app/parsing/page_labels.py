"""Page label detection — distinguishing the *physical* page index (1, 2,
3... in PDF order) from the *printed* label a reader sees (which might
restart, use roman numerals for a preface, or use Arabic-Indic digits or
abjad letters).

Two strategies, tried in order:

1. The PDF's own page-label catalog (`/PageLabels`), when the document
   declares one — PyMuPDF exposes this as `doc.get_page_labels()`. This
   is authoritative when present: it's literally what the document's
   producer said the label should be, no heuristics needed.
2. A heuristic scan of the top/bottom ~10% of the rendered page for a
   short numeric/roman/abjad token — the original Phase 1 approach,
   extended here with Arabic-Indic digit support and abjad-as-page-number
   recognition (as opposed to abjad-as-chapter-marker, which hierarchy.py
   handles separately).
"""

import re

import fitz  # PyMuPDF

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


def _heuristic_label(page: "fitz.Page") -> str | None:
    """Looks for a short numeric/lettered token in the top/bottom ~10% of
    the page — where a printed page number conventionally sits."""
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


def build_catalog_label_map(doc: "fitz.Document") -> dict[int, str]:
    """Reads the PDF's declared /PageLabels ranges, if any, into a
    {physical_page_index (0-based): printed_label} map. Returns an empty
    dict for documents with no page-label catalog — the caller falls
    back to the heuristic scan for every page in that case."""
    try:
        labels = doc.get_page_labels()
    except Exception:
        return {}

    if not labels:
        return {}

    result: dict[int, str] = {}
    for i in range(doc.page_count):
        try:
            label = doc.get_page_label(i)
        except Exception:
            label = None
        if label:
            result[i] = label
    return result


def detect_page_label(page: "fitz.Page", catalog_labels: dict[int, str], page_index: int) -> str | None:
    """page_index is 0-based (physical index into the document)."""
    if page_index in catalog_labels:
        return catalog_labels[page_index]
    return _heuristic_label(page)

"""Per-page PDF classification — spec item 3 of the OCR/Arabic-parsing
upgrade. Decides which extraction strategy a page needs *before*
extraction commits to one, using several signals together rather than
the old "no text blocks -> OCR, otherwise trust native text" rule in
document_parser_v2.py, which had two real failure modes:

    - A page with a broken/corrupted embedded font (garbled ToUnicode
      CMap) still has "text blocks" — PyMuPDF happily returns replacement
      characters — so it was silently accepted as good native text.
    - A page that's 90% a scanned image with one small native caption
      also has "text blocks", so it never triggered OCR for the image
      content at all.

Deliberately split into two halves:

    - `PageSignals` + `classify_page()`: pure, dependency-free decision
      logic. No PyMuPDF import, nothing that touches a real PDF — every
      input is a plain number. This is what's actually unit-testable in
      an environment without PyMuPDF installed (see the module docstring
      in tests/test_page_classifier.py for why that matters here).
    - `extract_page_signals()`: the one function that reads a real
      `fitz.Page` and reduces it to a `PageSignals` instance. This is the
      only part of this module that needs PyMuPDF at all.

document_parser_v2.py calls both in sequence; nothing about their split
is meant to be used independently in production, just independently
*tested*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# U+FFFD (the Unicode replacement character) is what you get back when a
# PDF's embedded font has a broken/missing ToUnicode CMap — PyMuPDF (or
# any extractor) can't map the glyph to a real character, so it emits
# this instead. A handful of these can be a legitimately unusual glyph;
# a page full of them is a corrupted extraction, not real text.
_REPLACEMENT_CHAR = "\ufffd"

# C0/C1 control characters that have no business appearing in extracted
# body text (line breaks/tabs are handled separately and excluded here).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class PageClass(str, Enum):
    NATIVE = "native"  # digitally generated, reliable extractable text, no significant image content
    SCANNED = "scanned"  # image-based; no reliable native text at all
    MIXED = "mixed"  # reliable native text AND a significant embedded image region
    CORRUPTED = "corrupted"  # native text exists but looks encoding-broken (replacement/control chars)
    EMPTY = "empty"  # no text, no meaningful image content — a genuinely blank page


@dataclass
class PageSignals:
    """Every number `classify_page` needs, with no PyMuPDF types mixed
    in — see `extract_page_signals` for how this gets built from a real
    page. Coverage fields are fractions of total page area, 0.0-1.0."""

    char_count: int
    word_count: int
    text_block_coverage: float
    image_coverage: float
    replacement_char_count: int
    control_char_count: int
    block_count: int

    @property
    def suspicious_char_rate(self) -> float:
        if self.char_count == 0:
            return 0.0
        return (self.replacement_char_count + self.control_char_count) / self.char_count

    @property
    def avg_word_length(self) -> float:
        if self.word_count == 0:
            return 0.0
        return self.char_count / self.word_count


@dataclass
class ClassifierConfig:
    """Thresholds — see Settings for the env-configurable copies of
    these; this dataclass exists so `classify_page` doesn't have to
    import app.config (keeping it dependency-free) and so tests can
    exercise specific threshold values directly."""

    min_native_chars: int = 20
    min_native_words: int = 5
    image_coverage_threshold: float = 0.35
    suspicious_char_rate_threshold: float = 0.02
    # A page can have SOME image content (a small logo, an inline icon)
    # without being "mixed" — this floor keeps trivial decorative images
    # from flipping an otherwise-clean native page to MIXED.
    trivial_image_coverage: float = 0.02
    # Below this average characters-per-word, extracted "words" are
    # implausibly short across the board — a classic symptom of a
    # font/CMap problem that doesn't (yet) show up as replacement chars,
    # since some encodings substitute plausible-looking but wrong glyphs
    # rather than U+FFFD outright.
    min_plausible_avg_word_length: float = 1.5


@dataclass
class PageClassificationResult:
    classification: PageClass
    signals: PageSignals
    warnings: list[str]


def classify_page(signals: PageSignals, config: ClassifierConfig | None = None) -> PageClassificationResult:
    """Pure decision function — spec item 3: "Do not rely only on
    whether extracted text is empty or whether layout blocks exist."
    Order of checks matters: corruption is checked before "has enough
    text", since a corrupted page can easily have plenty of *characters*
    that just aren't trustworthy ones."""
    cfg = config or ClassifierConfig()
    warnings: list[str] = []

    has_meaningful_image = signals.image_coverage >= cfg.trivial_image_coverage
    has_enough_native_text = signals.char_count >= cfg.min_native_chars and signals.word_count >= cfg.min_native_words

    if signals.char_count == 0 and not has_meaningful_image:
        return PageClassificationResult(PageClass.EMPTY, signals, warnings)

    suspicious_rate = signals.suspicious_char_rate
    if has_enough_native_text and suspicious_rate > cfg.suspicious_char_rate_threshold:
        warnings.append(
            f"suspicious/replacement character rate {suspicious_rate:.1%} exceeds "
            f"{cfg.suspicious_char_rate_threshold:.1%} — likely a broken font encoding"
        )
        return PageClassificationResult(PageClass.CORRUPTED, signals, warnings)

    if has_enough_native_text and 0 < signals.avg_word_length < cfg.min_plausible_avg_word_length:
        warnings.append(
            f"average extracted word length {signals.avg_word_length:.1f} chars is implausibly short — "
            "possible encoding corruption not caught by replacement-character detection"
        )
        return PageClassificationResult(PageClass.CORRUPTED, signals, warnings)

    if not has_enough_native_text:
        if has_meaningful_image:
            return PageClassificationResult(PageClass.SCANNED, signals, warnings)
        # Some text, but below the reliability floor, and no image to
        # fall back to either — treat as scanned so it still gets an
        # OCR attempt rather than silently keeping a handful of
        # untrustworthy characters as if they were a real page.
        if signals.char_count > 0:
            warnings.append(
                f"only {signals.char_count} native characters / {signals.word_count} words — below the "
                f"reliability floor ({cfg.min_native_chars} chars / {cfg.min_native_words} words)"
            )
            return PageClassificationResult(PageClass.SCANNED, signals, warnings)
        return PageClassificationResult(PageClass.EMPTY, signals, warnings)

    if has_meaningful_image and signals.image_coverage >= cfg.image_coverage_threshold:
        return PageClassificationResult(PageClass.MIXED, signals, warnings)

    return PageClassificationResult(PageClass.NATIVE, signals, warnings)


# --------------------------- signal extraction (needs PyMuPDF) ---------------------------


def count_suspicious_chars(text: str) -> tuple[int, int]:
    """(replacement_char_count, control_char_count) — split out as its
    own pure function (still no PyMuPDF dependency) so it's directly
    unit-testable against plain strings, including real Arabic text with
    diacritics, which must NOT be flagged as suspicious just because
    `unicodedata` combining marks are unfamiliar-looking."""
    replacement = text.count(_REPLACEMENT_CHAR)
    control = len(_CONTROL_CHAR_RE.findall(text))
    return replacement, control


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = rect
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _union_coverage(rects: list[tuple[float, float, float, float]], page_area: float) -> float:
    """Approximates the fraction of the page covered by a set of
    (possibly overlapping) rectangles. Exact polygon-union math is
    overkill for a coverage *signal* feeding a classification threshold
    — this sums areas and caps at 1.0, which over-counts overlapping
    regions but never under-counts, so it stays a conservative (i.e.
    "at least this much coverage") estimate rather than silently hiding
    genuine text/image presence."""
    if page_area <= 0:
        return 0.0
    total = sum(_rect_area(r) for r in rects)
    return min(1.0, total / page_area)


def extract_page_signals(page: "fitz.Page", layout_blocks: list) -> PageSignals:  # noqa: F821 - fitz typed loosely to avoid a hard import for type-checking only
    """Reduces a real PyMuPDF page (plus the already-parsed
    `layout_parser.LayoutBlock` list for it, so this doesn't re-walk
    `get_text('dict')` a second time) to a `PageSignals` instance.
    `layout_blocks` may be empty (a page with no native text at all) —
    that's a legitimate signal, not an error."""
    page_area = float(page.rect.width) * float(page.rect.height)

    text = "\n".join(b.text for b in layout_blocks)
    char_count = len(text)
    word_count = len(text.split())
    replacement_count, control_count = count_suspicious_chars(text)

    text_block_coverage = _union_coverage([b.bbox for b in layout_blocks], page_area)

    image_rects: list[tuple[float, float, float, float]] = []
    try:
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            image_rects.extend(tuple(r) for r in rects)
    except Exception:
        pass
    image_coverage = _union_coverage(image_rects, page_area)

    return PageSignals(
        char_count=char_count,
        word_count=word_count,
        text_block_coverage=text_block_coverage,
        image_coverage=image_coverage,
        replacement_char_count=replacement_count,
        control_char_count=control_count,
        block_count=len(layout_blocks),
    )

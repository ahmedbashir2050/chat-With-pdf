"""Lightweight language detection. Deliberately heuristic rather than
pulling in a new dependency (langdetect/fasttext etc.) for a binary
Arabic/English/mixed classification — the Unicode block a character
belongs to is a reliable enough signal for that specific job, and this
project's documents are explicitly scoped to Arabic/English content.
"""

import re

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Below this fraction of the minority script's share of all letters, we
# call the text single-language rather than "mixed" — a stray Arabic
# footnote in an otherwise-English report shouldn't flip the whole
# document to "mixed".
MIXED_THRESHOLD = 0.15


def detect_language(text: str) -> str | None:
    """Returns 'ar', 'en', 'mixed', or None if the text has no letters to
    classify (e.g. a page that's just a table of numbers)."""
    if not text or not text.strip():
        return None

    arabic_count = len(_ARABIC_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    total = arabic_count + latin_count

    if total == 0:
        return None

    arabic_ratio = arabic_count / total
    latin_ratio = latin_count / total

    if arabic_ratio >= MIXED_THRESHOLD and latin_ratio >= MIXED_THRESHOLD:
        return "mixed"
    return "ar" if arabic_ratio > latin_ratio else "en"


def detect_document_language(page_languages: list[str | None]) -> str | None:
    """Rolls up per-page detections into one document-level language.
    Majority vote, with 'mixed' winning any tie against a single script
    since that's the more informative (and more common in practice for
    genuinely bilingual documents) answer."""
    votes = [lang for lang in page_languages if lang]
    if not votes:
        return None

    counts = {lang: votes.count(lang) for lang in set(votes)}
    if len(set(votes)) > 1 and "mixed" not in counts:
        # Saw both 'ar' and 'en' pages but no page individually flagged
        # 'mixed' — the document as a whole still is.
        if "ar" in counts and "en" in counts:
            return "mixed"
    return max(counts, key=counts.get)

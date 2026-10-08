"""OCR/extraction quality gate — spec item 8. Decides, per page, whether
extracted content is trustworthy enough to enter the RAG index as-is
(`accepted`), should be retried with a different extraction strategy
(`needs_retry`), is borderline enough that a human should look at it
before it's trusted (`needs_review`), or has exhausted its retry budget
without ever becoming trustworthy (`failed`).

Same split as page_classifier.py, for the same reason: `compute_quality_score`
and `gate_quality` are pure functions over plain numbers (fully
unit-testable without PyMuPDF or any OCR engine installed); the caller
in document_parser_v2.py is what wires real page/OCR data into them.

Non-negotiable requirement this module exists to satisfy: "Never claim
that OCR can guarantee absolutely zero errors. Instead, implement quality
controls that detect unreliable extraction, retry automatically, and
prevent low-quality or corrupted content from silently entering the RAG
index." `compute_quality_score` never fabricates a confidence value —
when the OCR engine/provider genuinely didn't return one, `ocr_confidence`
stays `None` and the score is computed from the other, always-available
signals instead (spec item 8: "Do not fabricate confidence values when
the OCR engine does not provide them. Represent unavailable confidence
as null and use other signals.").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .page_classifier import PageClass, PageSignals


class QualityStatus(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_RETRY = "needs_retry"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class SourceType(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    MIXED = "mixed"  # native text + region-level OCR merged onto the same page


@dataclass
class QualityGateConfig:
    """Thresholds — see Settings for the env-configurable copies; kept
    as a separate dataclass for the same dependency-free-testing reason
    as ClassifierConfig (page_classifier.py)."""

    accept_score_threshold: float = 0.75
    retry_score_threshold: float = 0.5  # below this (and retries remain) -> needs_retry, not needs_review/failed
    review_score_threshold: float = 0.3  # below accept but at/above this (retries exhausted) -> needs_review
    max_retries: int = 2


@dataclass
class QualityAssessment:
    status: QualityStatus
    score: float | None  # None only when truly no signal exists to score at all (e.g. a page skipped entirely)
    classification: PageClass
    source_type: SourceType
    warnings: list[str] = field(default_factory=list)
    retry_count: int = 0
    retry_reasons: list[str] = field(default_factory=list)


def compute_quality_score(
    signals: PageSignals,
    classification: PageClass,
    ocr_confidence: float | None = None,
    retry_count: int = 0,
) -> float:
    """A 0.0-1.0 composite score from whatever signals are actually
    available — never a stand-in for a real probability (see this
    module's docstring), just an engineering heuristic for the gate
    below to threshold against. Scoring by classification:

    - EMPTY pages score 1.0: there's genuinely nothing wrong with a
      blank page, and the gate should never flag "no content" on a page
      that legitimately has none as a quality problem to retry.
    - CORRUPTED pages score low, driven by the same suspicious-char-rate
      signal that produced the classification in the first place, since
      that IS the quality problem for this page.
    - NATIVE/MIXED pages score from text density + suspicious-char
      penalty + (if this is genuinely an OCR/mixed page) the OCR
      confidence when one was actually provided.
    - SCANNED pages score primarily from `ocr_confidence` when
      available; when it isn't (many local OCR engines/providers don't
      expose one, and it must never be fabricated), fall back to text
      density signals from whatever native text DID come through
      (usually little to none, hence a lower baseline for this branch).

    `retry_count` applies a small, capped penalty — a page that needed
    two retries to become readable is less trustworthy than one that was
    clean on the first pass, even once it's technically "accepted".
    """
    if classification == PageClass.EMPTY:
        return 1.0

    if classification == PageClass.CORRUPTED:
        # Directly driven by how bad the suspicious-char rate is —
        # already >threshold by definition of being classified
        # CORRUPTED, so this only ever lands in the low range.
        penalty = min(1.0, signals.suspicious_char_rate * 4)
        score = max(0.0, 1.0 - penalty)
    elif classification == PageClass.SCANNED:
        if ocr_confidence is not None:
            score = max(0.0, min(1.0, ocr_confidence))
        else:
            # No confidence signal available at all (spec: never
            # fabricate one) — fall back to a text-density estimate,
            # the same one NATIVE/MIXED pages use, discounted slightly
            # to reflect that density alone can't fully verify accuracy
            # the way a real per-word OCR confidence score could. NOT
            # capped far below the accept threshold — a genuinely good,
            # substantial OCR transcript must still be reachable as
            # ACCEPTED, or every scanned page would end up stuck at
            # needs_review/failed by construction regardless of quality,
            # which would defeat indexing scanned documents at all.
            density = min(1.0, signals.word_count / 40) if signals.word_count else 0.0
            score = density * 0.9
    else:  # NATIVE or MIXED
        # By the time a page reaches this branch, `classify_page` has
        # already confirmed it clears the native-text reliability floor
        # (min_native_chars/words) and shows no corruption signal — so
        # word COUNT beyond that floor isn't actually informative about
        # trustworthiness (a short, clean title page is not lower
        # quality than a long one), only suspicious-character rate is.
        # Scoring density here was an earlier, wrong design: it made a
        # legitimately short-but-clean page (or a MIXED page whose
        # native portion is short) fail to reach ACCEPTED for no real
        # quality reason, which would have silently excluded good
        # content from the index — exactly what this gate exists to
        # prevent, just from the opposite (over-cautious) direction.
        suspicious_penalty = min(1.0, signals.suspicious_char_rate * 4)
        score = max(0.0, 0.95 - suspicious_penalty)
        if classification == PageClass.MIXED and ocr_confidence is not None:
            # A mixed page's score should reflect both the (reliable)
            # native portion and the (less certain) OCR'd image-region
            # portion — average rather than letting the strong native
            # score fully mask a poor OCR result on the image regions.
            score = (score + max(0.0, min(1.0, ocr_confidence))) / 2

    retry_penalty = min(0.15, 0.05 * retry_count)
    return max(0.0, min(1.0, score - retry_penalty))


def gate_quality(
    score: float | None,
    classification: PageClass,
    retry_count: int,
    config: QualityGateConfig | None = None,
) -> QualityStatus:
    """Pure status decision. `score=None` is a distinct, legitimate
    input (see `compute_quality_score`'s docstring on never fabricating
    a value) — it always resolves to NEEDS_REVIEW, never ACCEPTED,
    since there's no signal to accept on."""
    cfg = config or QualityGateConfig()

    if classification == PageClass.EMPTY:
        return QualityStatus.ACCEPTED

    if score is None:
        return QualityStatus.NEEDS_REVIEW

    if score >= cfg.accept_score_threshold:
        return QualityStatus.ACCEPTED

    if retry_count < cfg.max_retries and score < cfg.retry_score_threshold:
        return QualityStatus.NEEDS_RETRY

    if score >= cfg.review_score_threshold:
        return QualityStatus.NEEDS_REVIEW

    return QualityStatus.FAILED


def assess_page_quality(
    signals: PageSignals,
    classification: PageClass,
    warnings: list[str],
    source_type: SourceType,
    ocr_confidence: float | None = None,
    retry_count: int = 0,
    retry_reasons: list[str] | None = None,
    config: QualityGateConfig | None = None,
) -> QualityAssessment:
    """Convenience wrapper combining `compute_quality_score` +
    `gate_quality` into one `QualityAssessment` — what document_parser_v2.py
    actually calls per page/retry-attempt."""
    score = compute_quality_score(signals, classification, ocr_confidence, retry_count)
    status = gate_quality(score, classification, retry_count, config)
    return QualityAssessment(
        status=status,
        score=score,
        classification=classification,
        source_type=source_type,
        warnings=list(warnings),
        retry_count=retry_count,
        retry_reasons=list(retry_reasons or []),
    )

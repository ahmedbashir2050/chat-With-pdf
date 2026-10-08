"""ClaimVerificationService — the Claim -> Evidence -> Citation grounding
stage (spec items 3-9, 16-18, 21, 26; semantic upgrade per the follow-up
spec items 1-28).

The rest of the RAG pipeline (retrieval, reranking, context management,
AnswerGeneratorService's LLM call) produces a *draft* answer. A citation
marker like "[p. 15]" existing in that draft only proves the page was
shown to the model — see citation_validator_service.py — it says nothing
about whether the sentence attached to it is actually true of that page's
content. This module closes that gap:

    draft answer
        -> split into atomic claims (ClaimExtractor)
        -> each claim checked against ONLY the document chunks the model
           was given, never outside/pretrained knowledge (EvidenceVerifier)
        -> unsupported/contradicted/uncertain claims are removed
           (AnswerRepairer) — fail-closed, per spec item 6
        -> grounded answer + evidence_coverage / citation_score /
           grounding_score (kept separate from the legacy confidence_score,
           per spec item 7 — that score is retrieval+citation-existence
           based and is NOT redefined here)

TWO-STAGE VERIFICATION (follow-up spec item 14). Lexical overlap alone
cannot tell "The system can process documents using FastAPI" apart from
its negation, cannot recognize a paraphrase, and cannot judge whether
"~100 users" licenses "exactly 100 users". So overlap is now Stage 1 — a
cheap deterministic filter that can only make a claim FAIL early (an
invalid citation, a missing number) or PASS early when the signal is
unambiguous (valid citation + very high overlap + no negation/approx/
high-risk-kind red flag). Everything else — paraphrases, negation,
causal claims, comparisons, anything the deterministic filter flagged as
ambiguous — is escalated to Stage 2, a semantic LLM verifier that
returns structured JSON (status/score/reason/supporting_pages) and is
ON by default (settings.claim_verification_use_llm=True — see follow-up
spec item 15). If no LLM is configured, or a call fails, Stage 2 falls
back to the Stage 1 heuristic's own (more conservative) verdict rather
than silently upgrading — this is strictly weaker than real semantic
verification and is documented as such in the final report, not hidden.
Chat history is never passed as evidence (spec item 26/17) — only the
document chunks actually supplied for this turn (plus, optionally, a
document-wide secondary lexical search — spec item 13 — which still
never leaves the user's own document).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from ..config import settings
from ..domain.citations import physical_page_citation_value
from ..domain.entities import DocumentChunk
from ..domain.interfaces import LLMService

# Same citation-marker shape citation_validator_service.py looks for —
# duplicated (not imported) because this module also needs to *strip*
# markers out of claim text before numeric extraction, which is a
# different use than existence-checking.
INLINE_CITATION_RE = re.compile(r"\[p\.\s*([^\]]+)\]", re.IGNORECASE)

logger = logging.getLogger(__name__)

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

_NOT_FOUND_EN = "I couldn't find that in this document."
_NOT_FOUND_AR = "لم أجد ذلك في هذا المستند."
# Public aliases for callers outside this module (e.g. qa_service.py's
# study-guide highlights) that need to recognize the fallback message
# without reaching into "private" names.
NOT_FOUND_MESSAGE_EN = _NOT_FOUND_EN
NOT_FOUND_MESSAGE_AR = _NOT_FOUND_AR

# --- numeric/date/money/percentage protection (spec item 17) ---
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_MONEY_RE = re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:1[5-9]|20)\d{2}\b")  # 1500-2099, catches dates without over-matching small counts
_DECIMAL_RE = re.compile(r"\b\d+\.\d+\b")
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){1,3}\b", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"\b\d{2,}\b")  # 2+ digit bare numbers (quantities, counts, stats)

# Follow-up spec item 10: "approximately 100" must not license "exactly
# 100". A number in the claim is treated as an unhedged/exact assertion
# unless the claim itself carries one of these hedges; if the evidence's
# own mention of that number IS hedged, an unhedged claim gets capped at
# PARTIALLY_SUPPORTED rather than SUPPORTED.
_HEDGE_WORDS = (
    "approximately", "about", "around", "roughly", "nearly", "circa",
    "~", "or so", "up to", "at least", "at most", "over", "under",
    "تقريبا", "حوالي", "نحو",
)

# Follow-up spec item 6: negation cues. Deliberately simple word-level
# matching (no real parse tree) — good enough to (a) force escalation to
# the semantic verifier when a negation word appears in either the claim
# or its evidence, since overlap alone cannot judge negation, and (b) as
# a conservative fallback when no LLM is available, to avoid the classic
# "high lexical overlap but flipped meaning" false-SUPPORTED failure
# mode. Arabic "لا"/"لم"/"ليس" are common function words and can produce
# false positives on their own — this is a known limitation (see final
# report), which is exactly why it only ever *escalates*, never
# auto-decides CONTRADICTED by itself.
_NEGATION_WORDS = {
    "not", "no", "never", "cannot", "can't", "cant", "doesn't", "doesnt", "don't", "dont",
    "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt", "weren't", "werent",
    "won't", "wont", "without", "unable", "fails to", "no longer", "none",
    "لا", "لم", "ليس", "غير", "بدون", "لن",
}

# "Significant" word tokens for the lexical-overlap fallback — short
# stopword-ish tokens are excluded so overlap isn't inflated by "the",
# "is", "and", etc. Kept intentionally simple (no external NLP deps).
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "of", "in", "on",
    "to", "for", "and", "or", "but", "with", "from", "by", "at", "not",
    "no", "do", "does", "did", "has", "have", "had", "can", "will",
    "would", "should", "could", "may", "might", "also", "than", "then",
    "into", "about", "over", "under", "such", "which", "who", "what",
}

_CONVERSATIONAL_RE = re.compile(
    r"^(i couldn'?t find|i could not find|let me know|feel free|would you like|"
    r"is there anything|does that|hope this helps|لم أجد|هل تريد|يسعدني)",
    re.IGNORECASE,
)

# A listing clause — "uses X, Y, Z, and W" / "includes A, B and C" — is
# exactly the shape spec item 8's worked example fabricates against
# (real items + one or two invented ones tacked onto a real citation).
# Matches the clause head so the item list after it can be checked
# member-by-member rather than as one lexical-overlap blob, where two
# real items can mathematically drown out one fabricated one.
_LIST_HEAD_RE = re.compile(
    r"\b(uses|includes|supports|consists of|comprises|contains|offers|provides|has)\b\s+",
    re.IGNORECASE,
)
_LIST_ITEM_SPLIT_RE = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.IGNORECASE)

# Follow-up spec item 22: "major" claims (absolute/superlative language:
# guarantees, 100%, always/never, totally secure...) get a heavier
# weight in evidence_coverage than an incidental minor fact like a
# release year, so one unsupported sweeping claim drags grounding_score
# down much more than one unsupported footnote does.
_MAJOR_CLAIM_RE = re.compile(
    r"\b(?:guarantee[sd]?|always|never|completely|totally|fully|entirely|"
    r"impossible|certain(?:ly)?|definitely|absolutely|no\s+risk|risk[- ]free|"
    r"perfectly|zero\s+(?:downtime|risk|errors?))\b"
    r"|100\s?%",
    re.IGNORECASE,
)
_MAJOR_CLAIM_WEIGHT = 2.0
_MINOR_CLAIM_WEIGHT = 1.0


def _is_major_claim(text: str) -> bool:
    return bool(_MAJOR_CLAIM_RE.search(text))


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNCERTAIN = "UNCERTAIN"
    NOT_FACTUAL = "NOT_FACTUAL"  # conversational filler — never scored, always kept


ACCEPTED_STATUSES = {ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED}
_STATUS_WEIGHT = {ClaimStatus.SUPPORTED: 1.0, ClaimStatus.PARTIALLY_SUPPORTED: 0.5}


def classify_claim_kind(text: str) -> str:
    """Best-effort tag for spec item 4's taxonomy — used for logging/
    debugging (spec item 29), not for different verification logic
    (every factual kind goes through the same claim -> evidence check)."""
    lowered = text.lower()
    if _PERCENT_RE.search(text) or _MONEY_RE.search(text) or _PLAIN_NUMBER_RE.search(text) or _DECIMAL_RE.search(text):
        return "numerical"
    if _YEAR_RE.search(text):
        return "date"
    if any(w in lowered for w in (" is defined as", " refers to", " means that", "is a term for")):
        return "definition"
    if any(w in lowered for w in (" because ", " due to ", " as a result", " causes ", " leads to ")):
        return "causal"
    if any(w in lowered for w in (" more than", " less than", " compared to", " whereas", " versus", " vs ")) or re.search(
        r"\b\w+er\s+than\b", lowered
    ):
        return "comparison"
    if any(w in lowered for w in ("therefore", "in conclusion", "overall,", "in summary")):
        return "conclusion"
    if "table" in lowered or "figure" in lowered:
        return "table"
    if "=" in text or any(sym in text for sym in ("∑", "∫", "√")):
        return "formula"
    return "factual"


def _extract_numeric_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for rx in (_PERCENT_RE, _MONEY_RE, _VERSION_RE, _DECIMAL_RE, _YEAR_RE, _PLAIN_NUMBER_RE):
        tokens.extend(m.group(0) for m in rx.finditer(text))
    # Dedup while preserving order; version numbers/decimals already
    # subsume their bare-digit substrings, but simple dedup is enough
    # here since we only need "is this exact figure present".
    seen = set()
    unique = []
    for t in tokens:
        key = re.sub(r"[^\w.%]", "", t.lower())
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def _normalize_number(tok: str) -> str:
    return re.sub(r"[,\s]", "", tok.lower())


def _numeric_present(token: str, evidence_text: str) -> bool:
    needle = _normalize_number(token)
    haystack = _normalize_number(evidence_text)
    return needle in haystack


def _significant_tokens(text: str) -> set[str]:
    words = re.findall(r"[\w\u0600-\u06FF]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) >= 2}


def _lexical_overlap(claim_text: str, evidence_text: str) -> float:
    claim_tokens = _significant_tokens(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _significant_tokens(evidence_text)
    matched = sum(1 for t in claim_tokens if t in evidence_tokens)
    return matched / len(claim_tokens)


def _negation_words_in(text: str) -> set[str]:
    lowered = f" {text.lower()} "
    found = set()
    for w in _NEGATION_WORDS:
        needle = w if _ARABIC_RE.search(w) else f" {w} "
        if needle in lowered or lowered.strip().startswith(w):
            found.add(w)
    return found


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?؟])\s+")


def _relevant_evidence_slice(bare_text: str, evidence_text: str) -> str:
    """Narrows a (possibly multi-sentence, multi-topic) evidence chunk
    down to just the sentence(s) that actually share vocabulary with the
    claim, before checking for negation words. Without this, one
    unrelated "not"/"no" elsewhere in a long chunk would falsely flag
    every claim checked against that chunk as a negation risk — the
    negation word has to at least be in a sentence about the same
    thing as the claim to be a meaningful signal."""
    claim_tokens = _significant_tokens(bare_text)
    if not claim_tokens:
        return evidence_text
    sentences = [s for s in _SENTENCE_BOUNDARY_RE.split(evidence_text) if s.strip()]
    if len(sentences) <= 1:
        return evidence_text
    relevant = [s for s in sentences if _significant_tokens(s) & claim_tokens]
    return " ".join(relevant) if relevant else evidence_text


def _negation_mismatch(claim_text: str, evidence_text: str) -> bool:
    """True when the claim's negation polarity can't be trusted from
    lexical overlap alone — either side mentions a negation cue. Overlap
    is symmetric to "X" vs "not X", so ANY negation cue anywhere in the
    claim or its (topically relevant slice of) evidence is enough to
    force escalation (follow-up spec item 6); it does not by itself
    decide CONTRADICTED vs SUPPORTED."""
    scoped_evidence = _relevant_evidence_slice(claim_text, evidence_text)
    return bool(_negation_words_in(claim_text) or _negation_words_in(scoped_evidence))


def _hedge_present_near(number_token: str, text: str, window: int = 40) -> bool:
    """Follow-up spec item 10: was this number stated as an
    approximation in `text`? Looks for a hedge word within `window`
    characters before the number's position."""
    lowered = text.lower()
    idx = lowered.find(_normalize_number(number_token).replace(",", ""))
    # normalize_number strips separators, so also try the raw token.
    if idx == -1:
        idx = lowered.find(number_token.lower())
    if idx == -1:
        return False
    start = max(0, idx - window)
    snippet = lowered[start:idx]
    return any(h in snippet for h in _HEDGE_WORDS)


def _extract_plain_numbers(text: str) -> list[float]:
    """Plain (non-percent/date/version) numbers for derived-value
    arithmetic (follow-up spec item 11) — years are excluded since
    summing years is never a meaningful "derivation"."""
    out = []
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", text):
        raw = m.group(0)
        if _YEAR_RE.fullmatch(raw):
            continue
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


_AGGREGATION_CUES = ("total", "combined", "altogether", "in all", "sum", "overall")

# Follow-up spec item 25 #5 ("similar terminology"): a claim can name a
# specific metric with the RIGHT number but the WRONG metric — "recall
# was 92%" when the evidence says precision was 92%. The number alone
# matching is not enough; if the claim names one of these specific
# terms, that same term (not just some number) must appear in the
# evidence, or this is escalated/rejected rather than trusted on a
# valid citation + number match alone.
_METRIC_TERMS = (
    "precision", "recall", "accuracy", "f1", "f1-score", "latency", "throughput",
    "error rate", "loss", "perplexity", "bleu", "rouge", "auc", "mae", "rmse",
)


def _metric_term_mismatch(bare_text: str, evidence_text: str) -> bool:
    lowered_claim = bare_text.lower()
    claim_terms = [t for t in _METRIC_TERMS if t in lowered_claim]
    if not claim_terms:
        return False
    lowered_evidence = evidence_text.lower()
    return not any(t in lowered_evidence for t in claim_terms)


def _derived_value_supported(claim_number: float, evidence_text: str, max_terms: int = 4) -> bool:
    """Deterministic arithmetic check only — the LLM is never asked to
    "do the math" (follow-up spec item 11 is explicit: never let the
    model perform unsupported arithmetic mentally). If `claim_number`
    equals the sum of some subset (up to `max_terms` values) of the
    numbers actually present in the evidence, the derivation is safe to
    accept."""
    from itertools import combinations

    candidates = [n for n in _extract_plain_numbers(evidence_text) if n != claim_number]
    if not candidates or len(candidates) > 8:  # cap subset search for performance
        candidates = candidates[:8]
    for r in range(2, min(max_terms, len(candidates)) + 1):
        for combo in combinations(candidates, r):
            if abs(sum(combo) - claim_number) < 1e-6:
                return True
    return False


@dataclass
class ClaimEvidence:
    """Structured claim -> evidence -> page mapping (spec item 9). The
    final answer text can still just show `[p. 15]`, but internally the
    backend knows exactly which chunk(s) and which page(s) that claim
    was checked against."""

    text: str
    kind: str
    cited_labels: list[str]
    evidence_chunks: list[DocumentChunk] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.UNCERTAIN
    score: float = 0.0
    line_index: int = 0
    # Set when `_check_enumeration` trims an unsupported item out of an
    # otherwise-supported list-style claim (spec item 8's "FastAPI,
    # Qdrant, PostgreSQL, and Redis" example) — the citation-free body
    # text to use instead of `text` when the claim is kept. `None` means
    # keep `text` unchanged.
    repaired_text: str | None = None
    # Human-readable justification (follow-up spec item 2/23) — from the
    # semantic verifier's own "reason" field when Stage 2 ran, or a short
    # description of which deterministic check decided it otherwise.
    # Logged for debugging, never sent to the client.
    reason: str = ""
    # Verified-safe citation pages (follow-up spec item 12) — ONLY pages
    # the verifier actually confirmed support this claim. The model's own
    # `[p. X]` marker is never trusted blindly; `physical_pages` (below,
    # derived from `evidence_chunks`) is what the final citation is drawn
    # from, and `supporting_pages` (set by the semantic verifier, as the
    # numeric-string page values it returned and that passed validation
    # against the actual evidence) narrows that further when Stage 2 ran.
    supporting_pages: list[str] | None = None

    @property
    def display_text(self) -> str:
        return self.repaired_text if self.repaired_text is not None else self.text

    @property
    def evidence_ids(self) -> list[int | str | None]:
        return [c.id for c in self.evidence_chunks]

    @property
    def physical_pages(self) -> list[int]:
        """The 1-based physical PDF page numbers that support this
        claim — e.g. `physical_pages = [12, 15]`. This is the ONLY page
        identity a claim's citation is ever drawn from; there is no
        printed-label/display-page concept anywhere in this pipeline
        (see domain/citations.py). Previously named `page_labels`,
        which had become misleading once the citation-display-label
        concept was removed entirely from the project — renamed here to
        make explicit that these are physical page numbers, nothing
        else."""
        if self.supporting_pages:
            return [int(p) for p in self.supporting_pages]
        seen: list[int] = []
        for c in self.evidence_chunks:
            if c.physical_page not in seen:
                seen.append(c.physical_page)
        return seen


@dataclass
class GroundingReport:
    original_answer: str
    grounded_answer: str
    claims: list[ClaimEvidence]
    retrieval_score: float
    evidence_coverage: float
    citation_score: float
    grounding_score: float

    @property
    def factual_claims(self) -> list[ClaimEvidence]:
        return [c for c in self.claims if c.kind != "conversational"]

    @property
    def unsupported_claims(self) -> list[ClaimEvidence]:
        return [c for c in self.factual_claims if c.status not in ACCEPTED_STATUSES]

    @property
    def supported_claims(self) -> list[ClaimEvidence]:
        return [c for c in self.factual_claims if c.status in ACCEPTED_STATUSES]


# --------------------------- claim extraction ---------------------------

# Splits on sentence-ending punctuation (., !, ?, Arabic ؟) followed by
# whitespace, OR on a line boundary — bullet points each become their
# own claim rather than being merged with neighboring bullets.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟])\s+")


def _mask_citation_periods(text: str) -> str:
    """`[p. 5]` contains a period-then-space, which would otherwise look
    like a sentence boundary to `_SENTENCE_SPLIT_RE` and split a claim
    right in the middle of its own citation marker. Temporarily swap
    that period for a sentinel byte before splitting, restored right
    after — see `_unmask_citation_periods`."""
    return INLINE_CITATION_RE.sub(lambda m: m.group(0).replace(".", "\x00"), text)


def _unmask_citation_periods(text: str) -> str:
    return text.replace("\x00", ".")


def _split_into_lines_and_sentences(answer_text: str) -> list[list[str]]:
    """Returns one list-of-sentences per line, preserving line structure
    so the repaired answer can be reassembled with the same paragraph/
    bullet layout the model produced."""
    lines = answer_text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append([])
            continue
        masked = _mask_citation_periods(stripped)
        sentences = [_unmask_citation_periods(s.strip()) for s in _SENTENCE_SPLIT_RE.split(masked) if s.strip()]
        result.append(sentences or [stripped])
    return result


class ClaimExtractor:
    def extract(self, answer_text: str) -> list[ClaimEvidence]:
        """Breaks a draft answer into atomic claims (spec item 4),
        tagging conversational filler as kind='conversational' so it's
        never dropped by the repair stage and never counted in
        evidence_coverage."""
        claims: list[ClaimEvidence] = []
        for line_idx, sentences in enumerate(_split_into_lines_and_sentences(answer_text)):
            for sentence in sentences:
                if len(sentence) < 3:
                    continue
                cited = [m.strip() for m in INLINE_CITATION_RE.findall(sentence)]
                bare_text = INLINE_CITATION_RE.sub("", sentence).strip()
                if not bare_text:
                    continue
                kind = "conversational" if _CONVERSATIONAL_RE.match(bare_text) else classify_claim_kind(bare_text)
                claims.append(ClaimEvidence(text=sentence, kind=kind, cited_labels=cited, line_index=line_idx))
        return claims


# --------------------------- evidence verification ---------------------------

# Follow-up spec item 3: strict, structured JSON verifier prompt. No free
# text is trusted — see `_parse_verifier_json` below, which fails closed
# (returns None -> Stage 2 treated as "didn't run") on anything that
# doesn't parse as the exact expected shape.
_SEMANTIC_VERIFY_SYSTEM_PROMPT = (
    "You are a document evidence verifier.\n"
    "Your ONLY source of truth is the supplied DOCUMENT EVIDENCE.\n"
    "You MUST NOT use pretrained knowledge, common knowledge, internet knowledge, "
    "assumptions, unstated implications, or information from previous assistant messages.\n\n"
    "Determine whether the CLAIM is supported by the DOCUMENT EVIDENCE.\n"
    "- SUPPORTED: the evidence explicitly or unambiguously entails the claim.\n"
    "- PARTIALLY_SUPPORTED: only part of the claim is supported.\n"
    "- CONTRADICTED: the evidence explicitly conflicts with the claim — including when "
    "the claim asserts the negation of what the evidence says, or vice versa.\n"
    "- UNSUPPORTED: the evidence does not establish the claim.\n"
    "- UNCERTAIN: the evidence is ambiguous and cannot safely establish the claim.\n"
    "If uncertain, do NOT mark the claim as SUPPORTED — never guess in the claim's favor.\n\n"
    "Be strict about:\n"
    "- Negation: check polarity carefully. Matching words do not mean matching meaning.\n"
    "- Causal language: do not accept a guarantee or causal claim from a weaker "
    "correlational, capability, or 'can help' statement.\n"
    "- Comparisons: both sides of a comparison must actually be in the evidence.\n"
    "- Precision: an approximate figure in the evidence ('approximately', 'about') does "
    "NOT license an exact figure in the claim — that is at most PARTIALLY_SUPPORTED.\n\n"
    "Respond with ONLY a single JSON object — no markdown fences, no extra text, no "
    "commentary before or after — in exactly this shape:\n"
    '{"status": "SUPPORTED|PARTIALLY_SUPPORTED|CONTRADICTED|UNSUPPORTED|UNCERTAIN", '
    '"score": <0.0-1.0>, "reason": "<short justification>", '
    '"supporting_pages": ["<page labels from the evidence that support this, or empty>"]}'
)


def _parse_verifier_json(reply: str | None) -> tuple[str, float, str, list[str]] | None:
    """Strict structured parsing (follow-up spec item 2: "Do not allow
    arbitrary text output from the verifier"). Returns None — never a
    guessed default — on anything that isn't the expected JSON shape, so
    the caller can fail closed rather than silently trusting free text."""
    if not reply:
        return None
    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    status = str(data.get("status", "")).strip().upper()
    if status not in ClaimStatus.__members__:
        return None
    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    reason = str(data.get("reason") or "").strip()
    pages = data.get("supporting_pages") or []
    if isinstance(pages, (str, int, float)):
        pages = [pages]
    pages = [str(p).strip() for p in pages if p is not None and str(p).strip()]
    return status, max(0.0, min(1.0, score)), reason, pages


class EvidenceVerifier:
    """Two-stage claim verification (follow-up spec item 14).

    Stage 1 (always runs, no LLM call, near-zero cost): deterministic
    checks that can only *definitively* decide a claim — an invalid
    citation or a missing number always fails outright; a valid citation
    with very high lexical overlap and no negation/approximation/
    high-risk-kind red flag passes outright. This is a huge share of
    real answers (plain factual sentences that closely echo their
    source), so most claims never need an LLM call at all.

    Stage 2 (semantic LLM verifier, on by default per follow-up spec
    item 15 — settings.claim_verification_use_llm): everything Stage 1
    couldn't confidently resolve — paraphrases, negation, causal claims,
    comparisons, hedged numbers — is escalated to a structured-JSON
    semantic verifier (see `_SEMANTIC_VERIFY_SYSTEM_PROMPT`/
    `_parse_verifier_json`). If no LLM is configured, or the call fails
    to parse, verification falls back to the Stage 1 heuristic's own
    (deliberately more conservative in that mode — e.g. any negation cue
    becomes UNCERTAIN rather than a guess) verdict. This fallback is
    strictly weaker than genuine semantic verification and is called out
    as a known limitation rather than presented as equivalent."""

    def __init__(self, llm_service: LLMService | None = None, use_llm: bool | None = None):
        self._llm = llm_service
        self._use_llm = settings.claim_verification_use_llm if use_llm is None else use_llm

    def verify(
        self,
        claim: ClaimEvidence,
        context_chunks: list[DocumentChunk],
        available_labels: dict[str, list[DocumentChunk]],
        full_document_chunks: list[DocumentChunk] | None = None,
    ) -> None:
        """Mutates `claim` in place, setting .status, .score, .reason,
        .supporting_pages and .evidence_chunks. `full_document_chunks`
        (optional) enables Stage 2's secondary-evidence-retrieval rescue
        (follow-up spec item 13) — never anything beyond the user's own
        uploaded document."""
        if claim.kind == "conversational":
            claim.status = ClaimStatus.NOT_FACTUAL
            return

        cited_valid = [label for label in claim.cited_labels if label.lower() in available_labels]
        cited_invalid = [label for label in claim.cited_labels if label.lower() not in available_labels]

        if cited_invalid and not cited_valid:
            # A citation pointing at a page that was never in the
            # context is a citation-level hallucination in its own
            # right (spec items 8, 22) — never allowed to survive, even
            # if the sentence's wording happens to resemble real
            # content elsewhere. Never trust the model's own page
            # number (follow-up spec item 12): the fail-closed choice is
            # to drop the claim, not "fix" the citation to a guess — the
            # only rescue path is a genuine secondary search below.
            claim.evidence_chunks = []
            claim.status, claim.score = ClaimStatus.UNSUPPORTED, 0.0
            claim.reason = "cited page is not part of the supplied evidence"
            self._maybe_secondary_retrieval(claim, full_document_chunks)
            return

        if cited_valid:
            evidence_chunks = [c for label in cited_valid for c in available_labels[label.lower()]]
        else:
            # No citation to anchor to — fall back to the whole context
            # the model saw as the candidate evidence pool. This never
            # reaches into chat history or outside knowledge; only
            # `context_chunks`, exactly what was supplied for this turn.
            evidence_chunks = list(context_chunks)
        claim.evidence_chunks = evidence_chunks

        evidence_text = "\n".join(c.text for c in evidence_chunks)
        # Numeric extraction/overlap must ignore the citation marker
        # itself (`[p. 999]` contains a bare number that is NOT a
        # factual claim about "999") — use the claim text with any
        # `[p. X]` markers stripped for all content analysis below.
        bare_text = INLINE_CITATION_RE.sub("", claim.text).strip()
        numeric_tokens = _extract_numeric_tokens(bare_text)
        negation_risk = _negation_mismatch(bare_text, evidence_text)
        # "guarantees"/"always"/"100% secure"-style absolute language is
        # exactly the shape a real fabrication tends to take riding on
        # top of a weaker, real statement (follow-up spec item 8) — treat
        # it as high-risk just like causal/comparison/conclusion kinds,
        # forcing semantic escalation rather than letting lexical overlap
        # alone wave it through.
        high_risk_kind = claim.kind in ("causal", "comparison", "conclusion") or _is_major_claim(bare_text)

        if numeric_tokens:
            self._verify_numeric(claim, bare_text, evidence_text, numeric_tokens, cited_valid, full_document_chunks)
            return

        # Non-numeric claim.
        overlap = _lexical_overlap(bare_text, evidence_text)
        word_count = len(bare_text.split())

        stage1_confident_pass = (
            not negation_risk
            and not high_risk_kind
            and ((cited_valid and overlap >= 0.5) or overlap >= 0.6)
        )
        if stage1_confident_pass:
            claim.status = ClaimStatus.SUPPORTED
            claim.score = max(overlap, 0.6 if cited_valid else overlap)
            claim.reason = "high lexical overlap with cited evidence (Stage 1)"
            self._check_enumeration(claim, bare_text, evidence_text)
            return

        if self._use_llm and self._llm is not None:
            if self._verify_with_llm_structured(claim, bare_text, evidence_text):
                if claim.status in ACCEPTED_STATUSES:
                    self._check_enumeration(claim, bare_text, evidence_text)
                if claim.status not in ACCEPTED_STATUSES:
                    self._maybe_secondary_retrieval(claim, full_document_chunks, bare_text)
                return

        # Stage 2 unavailable or failed to parse — conservative
        # heuristic fallback (weaker than real semantic verification;
        # see class docstring and the final report's "remaining risks").
        if negation_risk:
            claim.status, claim.score = ClaimStatus.UNCERTAIN, 0.0
            claim.reason = "negation cue present; cannot verify polarity without semantic check"
        elif high_risk_kind and overlap < 0.6:
            claim.status, claim.score = ClaimStatus.UNCERTAIN, overlap
            claim.reason = f"'{claim.kind}' claims require semantic verification to accept"
        elif cited_valid or overlap >= settings.claim_support_threshold or word_count <= 4:
            claim.status = ClaimStatus.SUPPORTED
            claim.score = max(overlap, 0.6 if cited_valid else overlap)
            claim.reason = "lexical overlap heuristic (Stage 2 unavailable)"
        elif overlap >= settings.claim_partial_threshold:
            claim.status, claim.score = ClaimStatus.PARTIALLY_SUPPORTED, overlap
            claim.reason = "partial lexical overlap heuristic (Stage 2 unavailable)"
        else:
            claim.status, claim.score = ClaimStatus.UNSUPPORTED, overlap
            claim.reason = "no lexical overlap with evidence"

        if claim.status in ACCEPTED_STATUSES:
            self._check_enumeration(claim, bare_text, evidence_text)
        if claim.status not in ACCEPTED_STATUSES:
            self._maybe_secondary_retrieval(claim, full_document_chunks, bare_text)

    def _verify_numeric(
        self,
        claim: ClaimEvidence,
        bare_text: str,
        evidence_text: str,
        numeric_tokens: list[str],
        cited_valid: list[str],
        full_document_chunks: list[DocumentChunk] | None,
    ) -> None:
        missing = [t for t in numeric_tokens if not _numeric_present(t, evidence_text)]
        if missing:
            # Follow-up spec item 11: a missing number might be a safe,
            # deterministic derivation (e.g. "50 total" from "20" + "30"
            # actually present in the evidence) rather than a
            # fabrication — but ONLY via real arithmetic on real
            # evidence numbers, never an LLM "doing the math" mentally.
            if any(cue in bare_text.lower() for cue in _AGGREGATION_CUES):
                for tok in missing:
                    try:
                        value = float(_normalize_number(tok).rstrip("%"))
                    except ValueError:
                        continue
                    if _derived_value_supported(value, evidence_text):
                        claim.status, claim.score = ClaimStatus.SUPPORTED, 0.8
                        claim.reason = "value matches deterministic sum of evidence figures"
                        return
            # Don't fail the whole sentence yet — a fabricated figure is
            # often riding along inside an otherwise-real multi-clause/
            # list sentence; try to salvage via enumeration-splitting,
            # then a semantic second opinion, then secondary retrieval.
            claim.status, claim.score = ClaimStatus.UNSUPPORTED, 0.0
            claim.reason = "figure not present in evidence"
            self._check_enumeration(claim, bare_text, evidence_text)
            if claim.status not in ACCEPTED_STATUSES and self._use_llm and self._llm is not None:
                self._verify_with_llm_structured(claim, bare_text, evidence_text)
            if claim.status not in ACCEPTED_STATUSES:
                self._maybe_secondary_retrieval(claim, full_document_chunks, bare_text)
            return

        # The figure itself is present — but was it stated as an
        # approximation in the evidence while the claim asserts it as
        # exact (follow-up spec item 10)? That overstates the evidence
        # and is at most partial support.
        approx_violation = any(
            _hedge_present_near(t, evidence_text) and not _hedge_present_near(t, bare_text) for t in numeric_tokens
        )
        negation_risk = _negation_mismatch(bare_text, evidence_text)
        metric_mismatch = _metric_term_mismatch(bare_text, evidence_text)
        overlap = _lexical_overlap(bare_text, evidence_text)
        stage1_pass = (
            (cited_valid or overlap >= 0.5) and not approx_violation and not negation_risk and not metric_mismatch
        )

        if stage1_pass:
            claim.status, claim.score = ClaimStatus.SUPPORTED, max(overlap, 0.6)
            claim.reason = "figure matches evidence exactly (Stage 1)"
            self._check_enumeration(claim, bare_text, evidence_text)
            return

        if self._use_llm and self._llm is not None:
            if self._verify_with_llm_structured(claim, bare_text, evidence_text):
                if claim.status in ACCEPTED_STATUSES:
                    self._check_enumeration(claim, bare_text, evidence_text)
                return

        if approx_violation:
            claim.status, claim.score = ClaimStatus.PARTIALLY_SUPPORTED, overlap
            claim.reason = "evidence states this figure as approximate; claim asserts it as exact"
        elif negation_risk:
            claim.status, claim.score = ClaimStatus.UNCERTAIN, 0.0
            claim.reason = "negation cue present; cannot verify polarity without semantic check"
        elif metric_mismatch:
            claim.status, claim.score = ClaimStatus.UNCERTAIN, 0.0
            claim.reason = "claim names a specific metric not found alongside this figure in the evidence"
        else:
            claim.status, claim.score = ClaimStatus.PARTIALLY_SUPPORTED, overlap
            claim.reason = "figure present but low overall overlap (Stage 2 unavailable)"
        self._check_enumeration(claim, bare_text, evidence_text)

    def _check_enumeration(self, claim: ClaimEvidence, bare_text: str, evidence_text: str) -> None:
        """Spec item 8 worked example: a sentence can be lexically
        'mostly' supported while smuggling in one fabricated list item
        (real citation, real items, plus an invented one). Split the
        item list after a listing verb and check each item's own
        significant tokens against the evidence individually; drop
        items with zero support and rewrite the sentence with only the
        supported ones, rather than either keeping the fabricated item
        or discarding the whole (mostly-true) sentence."""
        head_match = _LIST_HEAD_RE.search(bare_text)
        if not head_match:
            return
        head, tail = bare_text[: head_match.end()], bare_text[head_match.end() :]
        tail = tail.rstrip(" .")
        items = [i.strip() for i in _LIST_ITEM_SPLIT_RE.split(tail) if i.strip()]
        if len(items) < 3:
            return  # too ambiguous to safely split below 3 items

        evidence_tokens = _significant_tokens(evidence_text)
        kept, dropped = [], []
        for item in items:
            item_numeric = _extract_numeric_tokens(item)
            if item_numeric and any(not _numeric_present(t, evidence_text) for t in item_numeric):
                dropped.append(item)
                continue
            item_tokens = _significant_tokens(item)
            if not item_tokens or (item_tokens & evidence_tokens):
                kept.append(item)
            else:
                dropped.append(item)

        if not dropped:
            return
        if not kept:
            claim.status, claim.score = ClaimStatus.UNSUPPORTED, 0.0
            claim.repaired_text = None
            return

        if len(kept) == 1:
            joined = kept[0]
        elif len(kept) == 2:
            joined = f"{kept[0]} and {kept[1]}"
        else:
            joined = ", ".join(kept[:-1]) + ", and " + kept[-1]
        claim.repaired_text = f"{head}{joined}."
        claim.status = ClaimStatus.PARTIALLY_SUPPORTED
        claim.score = len(kept) / len(items)
        claim.reason = f"{len(dropped)} of {len(items)} listed item(s) not found in evidence and removed"

    def _verify_with_llm_structured(self, claim: ClaimEvidence, bare_text: str, evidence_text: str) -> bool:
        """Stage 2. Receives ONLY the claim + this claim's evidence text
        — no chat history, no outside knowledge (spec item 5/26).
        Returns True iff a valid structured verdict was obtained (so the
        caller knows whether Stage 2 actually ran); False means "fell
        back to Stage 1's heuristic verdict", never "trust it anyway"."""
        try:
            evidence_blocks = [f"[p. {physical_page_citation_value(c)}] {c.text}" for c in claim.evidence_chunks]
            evidence_blob = "\n\n".join(evidence_blocks) if evidence_blocks else (evidence_text or "(no evidence retrieved)")
            user_content = f"CLAIM: {bare_text}\n\nDOCUMENT EVIDENCE:\n{evidence_blob}"
            reply = self._llm.complete(
                [
                    {"role": "system", "content": _SEMANTIC_VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
            )
            parsed = _parse_verifier_json(reply)
            if parsed is None:
                return False
            status_str, score, reason, supporting_pages = parsed
            status = ClaimStatus[status_str]

            # Follow-up spec item 12: never trust the verifier's page
            # numbers blindly — only pages that are actually among the
            # evidence chunks we gave it are kept.
            evidence_pages = {physical_page_citation_value(c).strip().lower() for c in claim.evidence_chunks}
            verified_pages = [p for p in supporting_pages if p.strip().lower() in evidence_pages]

            if status == ClaimStatus.SUPPORTED and evidence_pages and not verified_pages:
                # Claimed SUPPORTED but couldn't point at a real
                # supporting page from its own evidence — don't take
                # that at face value.
                status = ClaimStatus.PARTIALLY_SUPPORTED
                score = min(score, 0.6)

            claim.status = status
            claim.score = score
            claim.reason = (reason or "semantic verifier")[:300]
            if verified_pages:
                claim.supporting_pages = verified_pages
            return True
        except Exception:
            # Any LLM/parsing failure fails closed: the caller falls
            # back to the Stage 1 heuristic rather than trusting a
            # partially-received or malformed response.
            return False

    def _maybe_secondary_retrieval(
        self, claim: ClaimEvidence, full_document_chunks: list[DocumentChunk] | None, bare_text: str | None = None
    ) -> None:
        """Follow-up spec item 13: the retriever may simply have picked
        the wrong chunk for THIS claim even though the document does
        contain the answer elsewhere. Does a cheap lexical search over
        the rest of the user's own document (never the internet, never
        other users' documents) and re-verifies against whatever it
        finds — only ever upgrades a claim that's currently failing; if
        nothing better turns up, the existing (failing) verdict stands."""
        if not full_document_chunks:
            return
        bare_text = bare_text if bare_text is not None else INLINE_CITATION_RE.sub("", claim.text).strip()
        already = {id(c) for c in claim.evidence_chunks}
        candidates = [c for c in full_document_chunks if id(c) not in already]
        if not candidates:
            return
        ranked = sorted(candidates, key=lambda c: _lexical_overlap(bare_text, c.text), reverse=True)
        top = [c for c in ranked[:3] if _lexical_overlap(bare_text, c.text) >= settings.claim_support_threshold]
        if not top:
            return
        new_evidence_text = "\n".join(c.text for c in top)
        numeric_tokens = _extract_numeric_tokens(bare_text)
        if numeric_tokens and any(not _numeric_present(t, new_evidence_text) for t in numeric_tokens):
            return  # still doesn't support the figure — don't rescue
        overlap = _lexical_overlap(bare_text, new_evidence_text)
        if overlap < 0.5:
            return
        claim.evidence_chunks = top
        claim.supporting_pages = None  # recompute physical_pages from the new evidence_chunks
        claim.cited_labels = []  # the original citation was wrong/missing — use the newly found page(s)
        claim.status, claim.score = ClaimStatus.SUPPORTED, overlap
        claim.reason = "found via secondary search of the document (not in the originally retrieved context)"


# --------------------------- answer repair ---------------------------


class AnswerRepairer:
    """Rewrites the draft answer so only SUPPORTED/PARTIALLY_SUPPORTED
    (and conversational) claims survive — Option A from spec item 6
    (remove, don't invent a replacement fact). Also backfills a missing
    citation on a kept claim when its evidence resolved to specific
    chunks, so the user-visible answer reflects the internal claim ->
    evidence -> page mapping (spec item 9) even when the model forgot to
    add `[p. X]` itself."""

    def repair(self, claims: list[ClaimEvidence], original_answer: str) -> str:
        by_line: dict[int, list[ClaimEvidence]] = {}
        for c in claims:
            by_line.setdefault(c.line_index, []).append(c)

        lines = original_answer.split("\n")
        rebuilt_lines = []

        for idx, _ in enumerate(lines):
            line_claims = by_line.get(idx, [])
            kept_sentences = []
            for c in line_claims:
                if c.status == ClaimStatus.NOT_FACTUAL or c.status in ACCEPTED_STATUSES:
                    kept_sentences.append(self._annotate(c))
            if kept_sentences:
                rebuilt_lines.append(" ".join(kept_sentences))
            elif not line_claims and not lines[idx].strip():
                rebuilt_lines.append("")  # preserve intentional blank lines

        grounded = "\n".join(rebuilt_lines).strip()
        grounded = re.sub(r"\n{3,}", "\n\n", grounded)

        factual = [c for c in claims if c.kind != "conversational"]
        if factual and not any(c.status in ACCEPTED_STATUSES for c in factual):
            return self._not_found_message(original_answer)

        unsupported_count = sum(1 for c in factual if c.status not in ACCEPTED_STATUSES)
        if unsupported_count >= settings.max_unsupported_claims and not grounded.strip():
            return self._not_found_message(original_answer)

        return grounded or self._not_found_message(original_answer)

    @staticmethod
    def _annotate(claim: ClaimEvidence) -> str:
        text = claim.display_text
        if claim.repaired_text is not None:
            # repaired_text has no citation marker of its own (stripped
            # before enumeration-splitting) — reattach whatever citation
            # the original sentence carried, or the evidence's own
            # physical page(s) if the model hadn't cited one.
            pages = claim.cited_labels or claim.physical_pages
            if not pages:
                return text
            marker = "".join(f"[p. {page}]" for page in pages[:3])
            return f"{text} {marker}"
        if claim.cited_labels or claim.kind == "conversational" or claim.status == ClaimStatus.NOT_FACTUAL:
            return text
        if not settings.citation_required:
            return text
        pages = claim.physical_pages
        if not pages:
            return text
        marker = "".join(f"[p. {page}]" for page in pages[:3])
        return f"{text} {marker}"

    @staticmethod
    def _not_found_message(original_answer: str) -> str:
        return _NOT_FOUND_AR if _ARABIC_RE.search(original_answer) else _NOT_FOUND_EN


# --------------------------- orchestrator ---------------------------


class ClaimVerificationService:
    """Wires extraction -> verification -> repair -> scoring together.
    This is the single entry point AnswerGeneratorService and QAService
    (long-context path) call — both normal RAG and long-context answers
    go through the exact same grounding stage (spec item 12)."""

    def __init__(self, llm_service: LLMService | None = None):
        self._extractor = ClaimExtractor()
        self._verifier = EvidenceVerifier(llm_service)

    def verify_and_repair(
        self,
        draft_answer: str,
        context_chunks: list[DocumentChunk],
        retrieval_score: float = 1.0,
        full_document_chunks: list[DocumentChunk] | None = None,
    ) -> GroundingReport:
        """`full_document_chunks` is optional and enables Stage 2's
        secondary-retrieval rescue (follow-up spec item 13) — pass the
        full set of chunks for this chat/document if available; when
        omitted, verification is scoped to `context_chunks` only, same
        as before."""
        available_labels: dict[str, list[DocumentChunk]] = {}
        for c in context_chunks:
            available_labels.setdefault(physical_page_citation_value(c).strip().lower(), []).append(c)

        claims = self._extractor.extract(draft_answer)
        for claim in claims:
            self._verifier.verify(claim, context_chunks, available_labels, full_document_chunks)

        grounded_answer = AnswerRepairer().repair(claims, draft_answer)

        # Follow-up spec item 22: weight "major" (absolute/superlative)
        # claims more heavily than incidental minor facts, so one
        # unsupported sweeping claim ("100% secure") drags
        # evidence_coverage down much further than one unsupported
        # footnote ("released in 2020") would.
        factual = [c for c in claims if c.kind != "conversational"]
        if factual:
            total_weight = 0.0
            supported_weight = 0.0
            for c in factual:
                w = _MAJOR_CLAIM_WEIGHT if _is_major_claim(c.text) else _MINOR_CLAIM_WEIGHT
                total_weight += w
                supported_weight += w * _STATUS_WEIGHT.get(c.status, 0.0)
            evidence_coverage = supported_weight / total_weight if total_weight else 1.0
        else:
            evidence_coverage = 1.0

        citation_score = self._citation_score(claims, grounded_answer, available_labels)
        retrieval_score = max(0.0, min(1.0, retrieval_score))
        grounding_score = 0.50 * evidence_coverage + 0.25 * citation_score + 0.25 * retrieval_score

        report = GroundingReport(
            original_answer=draft_answer,
            grounded_answer=grounded_answer,
            claims=claims,
            retrieval_score=retrieval_score,
            evidence_coverage=round(evidence_coverage, 4),
            citation_score=round(citation_score, 4),
            grounding_score=round(grounding_score, 4),
        )
        # Structured debug log (spec item 23/29) — counts, scores and a
        # per-claim trace (status/score/reason/evidence ids/supporting
        # pages), never the raw document/evidence text itself.
        logger.debug(
            "grounding: claims=%d supported=%d unsupported=%d retrieval=%.2f "
            "evidence_coverage=%.2f citation_score=%.2f grounding_score=%.2f",
            len(factual),
            len(report.supported_claims),
            len(report.unsupported_claims),
            report.retrieval_score,
            report.evidence_coverage,
            report.citation_score,
            report.grounding_score,
        )
        for c in factual:
            logger.debug(
                "claim_trace: %s",
                json.dumps(
                    {
                        "status": c.status.value,
                        "score": round(c.score, 3),
                        "reason": c.reason,
                        "physical_pages": c.physical_pages,
                        "evidence_ids": c.evidence_ids,
                    }
                ),
            )
        return report

    @staticmethod
    def _citation_score(
        claims: list[ClaimEvidence], grounded_answer: str, available_labels: dict[str, list[DocumentChunk]]
    ) -> float:
        """Fraction of claims that survived into the final answer and
        carry at least one *valid* citation (existing page, per spec
        item 8's citation-coverage requirement). Claims dropped by
        repair don't count against this — only what's actually shown
        to the user matters here."""
        kept_factual = [
            c
            for c in claims
            if c.kind != "conversational"
            and c.status in ACCEPTED_STATUSES
            and c.display_text.strip()
            and c.display_text in grounded_answer
        ]
        if not kept_factual:
            return 1.0
        scored = 0
        for c in kept_factual:
            pages = c.cited_labels or c.physical_pages
            if pages and any(str(page).strip().lower() in available_labels for page in pages):
                scored += 1
        return scored / len(kept_factual)

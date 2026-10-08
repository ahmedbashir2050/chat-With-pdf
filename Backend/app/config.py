"""Centralized configuration. Read once, validated with clear errors,
instead of scattered `os.environ[...]` reads at import time across
multiple modules (which was Phase 1 finding §3.5: a missing env var used
to crash the whole app at startup with a raw KeyError traceback)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    google_client_id: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    database_url: str = "sqlite:///./chat_with_pdf.db"
    embed_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"

    # --- Phase 4: reranking ---
    # 'local' (heuristic, zero extra deps/latency) is the default rather
    # than 'cross_encoder' so the app runs out of the box without
    # requiring a model download; see retrieval/reranker.py.
    rerank_provider: str = "local"  # 'local' | 'cross_encoder' | 'openai'
    rerank_candidate_count: int = 30  # chunks fetched from each of semantic/keyword search before reranking
    rerank_top_k: int = 8  # chunks kept after reranking, sent to the LLM
    rerank_semantic_weight: float = 0.3
    rerank_keyword_weight: float = 0.2
    rerank_weight: float = 0.5
    cross_encoder_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Phase 5: context management ---
    # Illustrative default matching the spec's own example (8000 available,
    # 7000 for context, ~1000 reserved for the answer) — not tied to the
    # actual context window of settings.chat_model, which is typically
    # much larger; tune per deployment via CONTEXT_TOKEN_BUDGET.
    context_token_budget: int = 7000

    # --- Phase 6: Qdrant vector search ---
    # Defaults match `docker-compose.yml`'s local/dev setup. `qdrant_api_key`
    # is None for local/docker (no auth) and set for Qdrant Cloud deployments.
    qdrant_url: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_api_key: str | None = None
    qdrant_https: bool = False
    qdrant_collection: str = "document_chunks"
    # Must match the embedding model's output dimensionality
    # (text-embedding-3-small = 1536). Changing embed_model without
    # updating this — and re-running the migration tool — will surface
    # as EmbeddingDimensionMismatch at upsert time.
    qdrant_vector_size: int = 1536
    qdrant_distance: str = "cosine"  # 'cosine' | 'dot' | 'euclid'
    qdrant_hnsw_m: int = 16
    qdrant_hnsw_ef_construct: int = 128
    qdrant_search_ef: int = 128
    qdrant_timeout_seconds: float = 10.0
    qdrant_max_retries: int = 3
    qdrant_retry_backoff_seconds: float = 0.5
    qdrant_batch_size: int = 256

    # --- Grounding / hallucination-resistance pipeline ---
    # Below this cosine-similarity score, the best-matching chunk still
    # isn't a real match — it's just the least-irrelevant thing in the
    # document. Was a hardcoded module constant in retrieval/retriever.py;
    # moved here so it's configurable without a code change (spec item 30).
    out_of_scope_similarity_threshold: float = 0.25
    # Claim-level grounding verifier (application/claim_verification_service.py).
    # Whether to call the LLM (with a strict, structured-JSON, "evidence
    # only" instruction) as Stage 2 semantic verification for claims
    # Stage 1's deterministic checks can't confidently resolve on their
    # own — paraphrases, negation, causal claims, comparisons, hedged
    # numbers. ON by default: lexical overlap alone cannot tell
    # "the system can process X" from its negation, and shipping without
    # semantic verification means silently accepting that failure mode.
    # Stage 1 still resolves the common/cheap cases (invalid citation,
    # missing number, near-identical high-overlap sentence) without an
    # LLM call at all, so this isn't "call the LLM for every claim" —
    # see EvidenceVerifier's docstring for the two-stage design. Turn
    # off only if you've measured the added latency/cost isn't
    # acceptable for your deployment and are consciously accepting
    # weaker (lexical-overlap-only) grounding as a result.
    claim_verification_use_llm: bool = True
    # A word-overlap ratio (claim vs. its evidence) at/above this is
    # treated as adequately supported for a non-numeric claim.
    claim_support_threshold: float = 0.12
    # A word-overlap ratio at/above this (but below claim_support_threshold)
    # is treated as PARTIALLY_SUPPORTED rather than UNSUPPORTED.
    claim_partial_threshold: float = 0.05
    # Overall grounding_score floor used by callers deciding whether to
    # trust a "mostly grounded" answer vs. fall back to "not found".
    grounding_min_score: float = 0.4
    # If an answer has this many or more UNSUPPORTED/CONTRADICTED/
    # UNCERTAIN claims, the whole answer is replaced with the
    # not-found fallback rather than partially repaired — guards
    # against a mostly-hallucinated answer that happens to keep one or
    # two innocuous supported sentences.
    max_unsupported_claims: int = 3
    # Whether a kept factual claim without any inline [p. X] citation
    # counts against citation_score, or is auto-annotated with the best
    # matching evidence chunk's page instead (see claim_verification_service.py).
    citation_required: bool = True

    # --- Page classification & OCR quality gate (parsing/page_classifier.py, parsing/quality_gate.py) ---
    # "Reliable native text" floor: below this many characters/words, a
    # page's native extraction isn't trusted even if PyMuPDF returned
    # some text — see PageClassifier's docstring for why char-count-only
    # (the old rule) isn't enough.
    page_min_native_chars: int = 20
    page_min_native_words: int = 5
    # A page's embedded-image area (as a fraction of page area) at/above
    # this is "significant" — used both to route MIXED pages (native
    # text is trustworthy, but a big image region should also be OCR'd)
    # and to route a low-text page to SCANNED rather than EMPTY.
    page_image_coverage_threshold: float = 0.35
    # A tiny logo/icon shouldn't flip an otherwise-clean text page to
    # MIXED — this is the floor below which image coverage is ignored
    # entirely for classification purposes.
    page_trivial_image_coverage: float = 0.02
    # Fraction of extracted characters that are the Unicode replacement
    # character or stray control characters, above which native text is
    # classified CORRUPTED (broken font/CMap) rather than trusted.
    page_suspicious_char_rate_threshold: float = 0.02
    # Average characters-per-extracted-word below this is implausible
    # for real text — a second, independent signal for corruption that
    # catches broken encodings that substitute wrong-but-valid glyphs
    # instead of emitting outright replacement characters.
    page_min_plausible_avg_word_length: float = 1.5

    # Quality-gate score thresholds (0.0-1.0) — see quality_gate.py for
    # the full scoring formula and why these are engineering thresholds,
    # not calibrated probabilities.
    quality_accept_score_threshold: float = 0.75
    quality_retry_score_threshold: float = 0.5
    quality_review_score_threshold: float = 0.3
    # Bounded retry budget per page (spec item 8: "bounded retries and
    # timeouts") — a page that's still bad after this many attempts is
    # marked needs_review/failed rather than retried forever.
    quality_max_retries: int = 2
    # DPI used to re-render a page for a retry OCR attempt — spec item 8
    # suggests "starting around 300 DPI"; the initial (non-retry)
    # rasterization stays at the existing 200 DPI default so a normal,
    # already-good scan isn't paying extra rendering/token cost for no
    # reason. Only a page that actually needs a retry pays the higher-DPI
    # cost.
    quality_ocr_retry_dpi: int = 300
    # Whether pages the gate marked `needs_review` still contribute their
    # chunks to the RAG index. Default False (excluded) is the safe
    # choice per this feature's #1 non-negotiable requirement — "prevent
    # low-quality or corrupted content from silently entering the RAG
    # index." `failed` pages are ALWAYS excluded regardless of this
    # setting; this only controls the more marginal `needs_review` tier.
    include_needs_review_in_rag: bool = False

def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in before starting the server."
        )
    return value


def load_settings() -> Settings:
    """Called once at startup (see main.py). Raising here, with a clear
    message, is deliberately better than letting a bare KeyError surface
    from whatever module happened to import first."""
    missing: list[str] = []
    values = {}
    for name in ("OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "JWT_SECRET"):
        try:
            values[name] = _require(name)
        except RuntimeError as e:
            missing.append(str(e))

    if missing:
        raise RuntimeError("Configuration error(s):\n" + "\n".join(missing))

    return Settings(
        openai_api_key=values["OPENAI_API_KEY"],
        google_client_id=values["GOOGLE_CLIENT_ID"],
        jwt_secret=values["JWT_SECRET"],
        rerank_provider=os.environ.get("RERANK_PROVIDER", "local"),
        rerank_candidate_count=int(os.environ.get("RERANK_CANDIDATE_COUNT", "30")),
        rerank_top_k=int(os.environ.get("RERANK_TOP_K", "8")),
        context_token_budget=int(os.environ.get("CONTEXT_TOKEN_BUDGET", "7000")),
        qdrant_url=os.environ.get("QDRANT_URL", "localhost"),
        qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
        qdrant_grpc_port=int(os.environ.get("QDRANT_GRPC_PORT", "6334")),
        qdrant_api_key=os.environ.get("QDRANT_API_KEY") or None,
        qdrant_https=os.environ.get("QDRANT_HTTPS", "false").lower() == "true",
        qdrant_collection=os.environ.get("QDRANT_COLLECTION", "document_chunks"),
        qdrant_vector_size=int(os.environ.get("QDRANT_VECTOR_SIZE", "1536")),
        qdrant_distance=os.environ.get("QDRANT_DISTANCE", "cosine"),
        qdrant_hnsw_m=int(os.environ.get("QDRANT_HNSW_M", "16")),
        qdrant_hnsw_ef_construct=int(os.environ.get("QDRANT_HNSW_EF_CONSTRUCT", "128")),
        qdrant_search_ef=int(os.environ.get("QDRANT_SEARCH_EF", "128")),
        qdrant_timeout_seconds=float(os.environ.get("QDRANT_TIMEOUT_SECONDS", "10.0")),
        qdrant_max_retries=int(os.environ.get("QDRANT_MAX_RETRIES", "3")),
        qdrant_retry_backoff_seconds=float(os.environ.get("QDRANT_RETRY_BACKOFF_SECONDS", "0.5")),
        qdrant_batch_size=int(os.environ.get("QDRANT_BATCH_SIZE", "256")),
        out_of_scope_similarity_threshold=float(os.environ.get("OUT_OF_SCOPE_SIMILARITY_THRESHOLD", "0.25")),
        claim_verification_use_llm=os.environ.get("CLAIM_VERIFICATION_USE_LLM", "true").lower() == "true",
        claim_support_threshold=float(os.environ.get("CLAIM_SUPPORT_THRESHOLD", "0.12")),
        claim_partial_threshold=float(os.environ.get("CLAIM_PARTIAL_THRESHOLD", "0.05")),
        grounding_min_score=float(os.environ.get("GROUNDING_MIN_SCORE", "0.4")),
        max_unsupported_claims=int(os.environ.get("MAX_UNSUPPORTED_CLAIMS", "3")),
        citation_required=os.environ.get("CITATION_REQUIRED", "true").lower() == "true",
        page_min_native_chars=int(os.environ.get("PAGE_MIN_NATIVE_CHARS", "20")),
        page_min_native_words=int(os.environ.get("PAGE_MIN_NATIVE_WORDS", "5")),
        page_image_coverage_threshold=float(os.environ.get("PAGE_IMAGE_COVERAGE_THRESHOLD", "0.35")),
        page_trivial_image_coverage=float(os.environ.get("PAGE_TRIVIAL_IMAGE_COVERAGE", "0.02")),
        page_suspicious_char_rate_threshold=float(os.environ.get("PAGE_SUSPICIOUS_CHAR_RATE_THRESHOLD", "0.02")),
        page_min_plausible_avg_word_length=float(os.environ.get("PAGE_MIN_PLAUSIBLE_AVG_WORD_LENGTH", "1.5")),
        quality_accept_score_threshold=float(os.environ.get("QUALITY_ACCEPT_SCORE_THRESHOLD", "0.75")),
        quality_retry_score_threshold=float(os.environ.get("QUALITY_RETRY_SCORE_THRESHOLD", "0.5")),
        quality_review_score_threshold=float(os.environ.get("QUALITY_REVIEW_SCORE_THRESHOLD", "0.3")),
        quality_max_retries=int(os.environ.get("QUALITY_MAX_RETRIES", "2")),
        quality_ocr_retry_dpi=int(os.environ.get("QUALITY_OCR_RETRY_DPI", "300")),
        include_needs_review_in_rag=os.environ.get("INCLUDE_NEEDS_REVIEW_IN_RAG", "false").lower() == "true",
    )


settings = load_settings()

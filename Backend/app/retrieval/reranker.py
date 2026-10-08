"""Reranker implementations. Each `BaseReranker` subclass has exactly one
job: given a query and a list of candidates, fill in each candidate's
`rerank_score` (0..1, higher = more relevant) — it does NOT decide the
final ordering or combine it with semantic/keyword scores; that's
`RerankerService`'s job (rerank_service.py), so the weighting formula
(spec item 5) lives in exactly one place regardless of which reranker
produced the score.

Three implementations, swappable via config (`Settings.rerank_provider`),
none of them tightly coupled to the rest of the pipeline beyond this
interface:

- `LocalReranker` — the Phase 3 heuristic (exact keyword/number/page/
  chapter matches), promoted to a real fallback rather than removed.
  Zero new dependencies, zero added latency — this is the default so the
  app runs out of the box without requiring a model download.
- `CrossEncoderReranker` — a real cross-encoder model (sentence-
  transformers), lazily loaded on first use, never at import/startup
  time. This is the "NotebookLM-grade" option, but it's an *optional*
  dependency: `sentence-transformers`/`torch` aren't in requirements.txt
  by default (multi-hundred-MB install), and this class falls back to
  `LocalReranker` on any import or load failure rather than taking the
  whole retrieval pipeline down.
- `OpenAIReranker` — a single batched LLM call asking for a 0-10
  relevance score per candidate. Costs one extra LLM call per question;
  offered as a middle ground between "no model" and "download a local
  model", not as the default.
"""

import json
import math
from abc import ABC, abstractmethod

from ..domain.interfaces import LLMService
from .models import QueryAnalysis, RetrievedChunk

# ---------------------------------------------------------------------
# LocalReranker tuning constants — same heuristic as Phase 3, but now
# normalized into a 0..1 rerank_score (previously an additive boost on
# top of the RRF score) so it combines meaningfully with semantic_score
# and keyword_score under RerankWeights.
# ---------------------------------------------------------------------
_EXACT_NUMBER_MATCH_WEIGHT = 0.35
_KEYWORD_COVERAGE_WEIGHT = 0.35
_PAGE_MATCH_WEIGHT = 0.15
_CHAPTER_OR_SECTION_MATCH_WEIGHT = 0.15


class BaseReranker(ABC):
    """Every reranker takes the full candidate list and returns it with
    `rerank_score` populated on each item — no filtering, no reordering.
    (`RerankerService` does the sorting/slicing, after combining scores.)
    This keeps every implementation trivially testable in isolation and
    means a reranker can never accidentally drop a candidate's metadata,
    satisfying spec item 7 by construction rather than by convention."""

    @abstractmethod
    def score(self, query: str, candidates: list[RetrievedChunk], analysis: QueryAnalysis | None = None) -> None:
        """Mutates each candidate's `.rerank_score` in place. Returning
        None (not a new list) is deliberate — it makes 'this never drops
        or reorders candidates' structurally obvious at the call site."""
        ...


class LocalReranker(BaseReranker):
    """Heuristic reranker: no model, no network call, no extra latency
    worth measuring. Good baseline and safe fallback for every other
    reranker in this module."""

    def score(self, query: str, candidates: list[RetrievedChunk], analysis: QueryAnalysis | None = None) -> None:
        if not candidates:
            return

        for r in candidates:
            text_lower = r.text.lower()
            signal = 0.0

            if analysis is not None:
                if analysis.numbers:
                    hits = sum(1 for n in analysis.numbers if n in r.text)
                    signal += _EXACT_NUMBER_MATCH_WEIGHT * min(hits / len(analysis.numbers), 1.0)

                if analysis.keywords:
                    hits = sum(1 for kw in analysis.keywords if kw in text_lower)
                    signal += _KEYWORD_COVERAGE_WEIGHT * min(hits / len(analysis.keywords), 1.0)

                if analysis.page_references and r.page in analysis.page_references:
                    signal += _PAGE_MATCH_WEIGHT

                chapter_hit = (
                    analysis.chapter_hint and r.chapter and analysis.chapter_hint.lower() in r.chapter.lower()
                )
                section_hit = (
                    analysis.section_hint and r.section and analysis.section_hint.lower() in r.section.lower()
                )
                if chapter_hit or section_hit:
                    signal += _CHAPTER_OR_SECTION_MATCH_WEIGHT
            else:
                # No query understanding available — fall back to plain
                # substring presence of the raw query terms.
                query_terms = [t for t in query.lower().split() if len(t) > 2]
                if query_terms:
                    hits = sum(1 for t in query_terms if t in text_lower)
                    signal = min(hits / len(query_terms), 1.0)

            r.rerank_score = min(signal, 1.0)


class CrossEncoderReranker(BaseReranker):
    """Real cross-encoder reranking via sentence-transformers. The model
    is loaded lazily — `__init__` does no I/O — and on any failure to
    import/load it, `score()` transparently falls back to
    `LocalReranker` rather than raising, since a missing optional
    dependency shouldn't take retrieval down.

    NOTE: `sentence-transformers` was NOT added to requirements.txt —
    this class was written and reviewed but could not be executed
    against a real model in the sandbox this was built in (no network
    access to download either the package or model weights). Install
    `sentence-transformers` and set `RERANK_PROVIDER=cross_encoder` to
    use it; verify in your own environment before relying on it.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._model = None
        self._load_failed = False
        self._fallback = LocalReranker()

    def _ensure_model(self):
        if self._model is not None or self._load_failed:
            return
        try:
            from sentence_transformers import CrossEncoder  # optional dependency

            self._model = CrossEncoder(self._model_name)
        except Exception:
            # Missing package, no internet to fetch weights, unsupported
            # platform, etc. — degrade rather than crash retrieval.
            self._load_failed = True

    def score(self, query: str, candidates: list[RetrievedChunk], analysis: QueryAnalysis | None = None) -> None:
        if not candidates:
            return

        self._ensure_model()
        if self._model is None:
            self._fallback.score(query, candidates, analysis)
            return

        # Batched: one predict() call over all (query, candidate) pairs,
        # not a Python loop of single-pair calls — this is what "batch
        # reranking" (spec item 8) means for a cross-encoder specifically,
        # since the model's own batching is far more efficient than N
        # separate forward passes.
        pairs = [(query, c.text) for c in candidates]
        try:
            raw_scores = self._model.predict(pairs)
        except Exception:
            self._fallback.score(query, candidates, analysis)
            return

        for c, raw in zip(candidates, raw_scores):
            # Cross-encoder logits are unbounded; squash to 0..1 so this
            # combines meaningfully with semantic_score/keyword_score
            # under the same RerankWeights formula regardless of which
            # reranker produced rerank_score.
            c.rerank_score = 1.0 / (1.0 + math.exp(-float(raw)))


class OpenAIReranker(BaseReranker):
    """LLM-based reranking: one batched prompt asking for a 0-10
    relevance score per candidate, parsed back into `rerank_score`.
    Offered per spec item 3 ("LLM-based reranking only if necessary") —
    NOT the default, since it costs one extra LLM call per question
    where `LocalReranker` costs nothing and `CrossEncoderReranker` costs
    only local compute."""

    def __init__(self, llm_service: LLMService):
        self._llm = llm_service
        self._fallback = LocalReranker()

    def score(self, query: str, candidates: list[RetrievedChunk], analysis: QueryAnalysis | None = None) -> None:
        if not candidates:
            return

        numbered = "\n\n".join(f"[{i}] {c.text[:500]}" for i, c in enumerate(candidates))
        prompt = (
            "Rate how relevant each numbered passage is to the query, on a 0-10 scale "
            "(10 = directly answers the query, 0 = completely unrelated). "
            'Respond with ONLY a JSON object mapping each index to its score, e.g. {"0": 7, "1": 2}. '
            "No commentary.\n\n"
            f"Query: {query}\n\nPassages:\n{numbered}"
        )

        try:
            raw = self._llm.complete([{"role": "user", "content": prompt}], temperature=0)
            scores = json.loads(raw.strip().strip("`").removeprefix("json").strip())
            for i, c in enumerate(candidates):
                value = scores.get(str(i))
                c.rerank_score = max(0.0, min(float(value), 10.0)) / 10.0 if value is not None else 0.0
        except Exception:
            # Malformed JSON, LLM call failure, unexpected shape — fall
            # back rather than leave rerank_score undefined for this batch.
            self._fallback.score(query, candidates, analysis)


# Backward-compatible alias — Phase 3's HeuristicReranker is Phase 4's
# LocalReranker under a new name; kept so anything still importing the
# old name doesn't break.
HeuristicReranker = LocalReranker

"""Entity extraction (spec item 3). Numbers, page references, and
chapter/section hints are NOT reimplemented here — they're pulled
straight from `retrieval.query_processing.analyze_query`, which already
extracts them (and is what `Retriever` has used since Phase 3). This
module adds the two entity types that module didn't need for retrieval
filtering but the richer query-understanding output calls for: dates and
technology/formula terms. People/organizations are deliberately not
attempted — see query/models.py's `Entities` docstring for why.
"""

import re

from ..retrieval.query_processing import analyze_query as _analyze_query_base
from .models import Entities

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")  # 1500-2099 — plausible document/historical years

# A small, curated technology/CS term list rather than an open-ended
# gazetteer — this is meant to catch the common case (a technical PDF
# chat mentioning a framework/algorithm by name) without pretending to
# be exhaustive. Matched case-insensitively as whole words.
_TECHNOLOGY_TERMS = [
    "flutter", "react", "python", "java", "javascript", "typescript", "swift", "kotlin",
    "cnn", "rnn", "lstm", "transformer", "bert", "gpt", "tensorflow", "pytorch",
    "sql", "nosql", "docker", "kubernetes", "rest api", "graphql", "html", "css",
    "widget", "statefulwidget", "statelesswidget",
]
_TECH_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _TECHNOLOGY_TERMS) + r")\b", re.IGNORECASE)

_FORMULA_RE = re.compile(r"\b(equation|formula|eq\.?)\s*(\d+)\b", re.IGNORECASE)


def extract_entities(question: str) -> Entities:
    base = _analyze_query_base(question, intent="specific")  # intent param unused by extraction itself

    dates = _YEAR_RE.findall(question)
    technologies = sorted({m.lower() for m in _TECH_RE.findall(question)})
    formulas = [f"{label} {num}" for label, num in _FORMULA_RE.findall(question)]

    return Entities(
        numbers=base.numbers,
        dates=dates,
        technologies=technologies,
        formulas=formulas,
        page_references=base.page_references,
        chapter_hint=base.chapter_hint,
        section_hint=base.section_hint,
    )

"""Intent classification (spec item 2) with the abstraction spec item 11
asks for: `BaseIntentClassifier`, so an LLM-based classifier can be
swapped in without touching QueryUnderstandingService. `LocalIntentClassifier`
is the default — regex/keyword rules, same style as the existing
`retrieval/query_understanding.py`'s EXPLAIN_PATTERN — because a rule can
usually tell "this says 'compare'" or "this says 'page 12'" without
paying for an LLM call on every single question (spec item 13: avoid
unnecessary LLM calls). `LLMIntentClassifier` exists for the harder
cases a human would find genuinely ambiguous, but isn't the default.
"""

import re
from abc import ABC, abstractmethod

from ..domain.interfaces import LLMService
from .models import Complexity, Intent

# Checked in priority order — several patterns can technically match one
# question ("compare X and Y in a table" mentions both comparison and
# structure), so the more specific/structural intent wins over a vaguer
# one further down the list.
_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    (Intent.PAGE_REQUEST, re.compile(r"\b(page|صفحة|ص)\s*\.?\s*\d+\b", re.IGNORECASE)),
    (Intent.CITATION_REQUEST, re.compile(r"\b(cite|citation|source for|where does .+ come from|ما هو مصدر|استشهاد)\b", re.IGNORECASE)),
    (Intent.COMPARISON, re.compile(r"\b(compare|comparison|vs\.?|versus|difference between|قارن|الفرق بين)\b", re.IGNORECASE)),
    (Intent.TIMELINE, re.compile(r"\b(timeline|chronology|order of events|in what order|history of|الجدول الزمني|بالترتيب الزمني)\b", re.IGNORECASE)),
    (Intent.TRANSLATION, re.compile(r"\b(translate|in (arabic|english)\??$|ترجم|بالعربي|بالانجليزي)\b", re.IGNORECASE)),
    (Intent.FORMULA_EXTRACTION, re.compile(r"\b(equation|formula|the formula for|معادلة|الصيغة)\b", re.IGNORECASE)),
    (Intent.CODE_EXPLANATION, re.compile(r"\b(this code|the code (snippet|block)|what does this function do|هذا الكود|الكود التالي)\b", re.IGNORECASE)),
    (Intent.EXAM_PREPARATION, re.compile(r"\b(exam prep\w*|prepare for (the )?(exam|test)|quiz me|test me|تحضير للامتحان)\b", re.IGNORECASE)),
    (Intent.STUDY_NOTES, re.compile(r"\b(study notes?|notes for|ملخص للمذاكرة|ملاحظات دراسية)\b", re.IGNORECASE)),
    (Intent.SUMMARY, re.compile(r"\b(summar(y|ize|ise)|tl;?dr|overview of|لخص|ملخص|اعطني ملخص)\b", re.IGNORECASE)),
    (Intent.DEFINITION, re.compile(r"\b(what is|what are|define|definition of|meaning of|ما هو|ما هي|عرّف|تعريف)\b", re.IGNORECASE)),
    (Intent.LIST, re.compile(r"\b(list|enumerate|what are the (types|kinds|steps|examples)|عدد|اذكر)\b", re.IGNORECASE)),
    (
        Intent.EXPLANATION,
        re.compile(
            r"\b(explain|why (?:is|does|do|did)|how does|how do|elaborate|walk me through|"
            r"teach me|help me understand|اشرح|فسّر|فسر|وضّح|وضح|لماذا|كيف يعمل|كيف تعمل|علّمني)\b",
            re.IGNORECASE,
        ),
    ),
    (Intent.FINDING_INFORMATION, re.compile(r"\b(find|locate|where (is|does|can i find)|أين|وين)\b", re.IGNORECASE)),
]

_BEGINNER_RE = re.compile(r"\b(simply|simple terms|like i'?m (five|new)|beginner|eli5|ببساطة|بشكل بسيط|كأني مبتدئ)\b", re.IGNORECASE)
_ADVANCED_RE = re.compile(r"\b(in depth|advanced|technical detail|rigorous(ly)?|بعمق|بشكل متقدم|تقني)\b", re.IGNORECASE)


class BaseIntentClassifier(ABC):
    @abstractmethod
    def classify(self, question: str) -> tuple[Intent, Complexity]: ...


class LocalIntentClassifier(BaseIntentClassifier):
    def classify(self, question: str) -> tuple[Intent, Complexity]:
        intent = Intent.QUESTION_ANSWERING  # default: a plain question with no stronger structural signal
        for candidate_intent, pattern in _PATTERNS:
            if pattern.search(question):
                intent = candidate_intent
                break

        if _BEGINNER_RE.search(question):
            complexity = Complexity.BEGINNER
        elif _ADVANCED_RE.search(question):
            complexity = Complexity.ADVANCED
        else:
            complexity = Complexity.INTERMEDIATE

        return intent, complexity


class LLMIntentClassifier(BaseIntentClassifier):
    """LLM-based alternative — one JSON-structured call per question.
    NOT the default (see module docstring); useful for a question a
    rule-based pass classifies as generic QUESTION_ANSWERING but which a
    deployment wants classified more specifically."""

    def __init__(self, llm_service: LLMService, fallback: BaseIntentClassifier | None = None):
        self._llm = llm_service
        self._fallback = fallback or LocalIntentClassifier()

    def classify(self, question: str) -> tuple[Intent, Complexity]:
        valid_intents = ", ".join(i.value for i in Intent)
        prompt = (
            f"Classify this question's intent as exactly one of: {valid_intents}. "
            "Also classify its complexity as exactly one of: beginner, intermediate, advanced. "
            'Respond with ONLY JSON: {"intent": "...", "complexity": "..."}. No commentary.\n\n'
            f"Question: {question}"
        )
        try:
            import json

            raw = self._llm.complete([{"role": "user", "content": prompt}], temperature=0)
            parsed = json.loads(raw.strip().strip("`").removeprefix("json").strip())
            return Intent(parsed["intent"]), Complexity(parsed["complexity"])
        except Exception:
            return self._fallback.classify(question)

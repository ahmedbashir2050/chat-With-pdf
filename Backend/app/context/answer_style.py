"""Answer style classification (spec item 10). Keyword-heuristic, same
approach as `retrieval/query_understanding.py`'s intent classification —
no model call needed to notice a question literally says "in bullet
points" or "compare X and Y". Summary requests are handled separately
(QAService's own SUMMARY_PATTERN branch, unchanged) since that's a
different retrieval *scope*, not just a formatting instruction — a style
here changes how an already-retrieved answer is written, not what's
retrieved.
"""

import re

_BULLET_RE = re.compile(r"\b(bullet\s*points?|as a list|in points|نقاط|في نقاط)\b", re.IGNORECASE)
_COMPARISON_RE = re.compile(
    r"\b(compare|comparison|vs\.?|versus|difference between|قارن|الفرق بين)\b", re.IGNORECASE
)
_STUDY_NOTES_RE = re.compile(r"\b(study notes?|notes for|ملخص للمذاكرة|ملاحظات دراسية)\b", re.IGNORECASE)
_EXAM_PREP_RE = re.compile(
    r"\b(exam prep\w*|prepare for (the )?(exam|test)|quiz me|test me|likely (exam )?questions?|تحضير للامتحان|اسئلة امتحان)\b",
    re.IGNORECASE,
)
_DETAILED_RE = re.compile(r"\b(in detail|detailed|thoroughly|comprehensive|بالتفصيل|بشكل مفصل)\b", re.IGNORECASE)
_ACADEMIC_RE = re.compile(r"\b(academic(ally)?|formal (tone|register|explanation)|scholarly|رسمي|أكاديمي|اكاديمي)\b", re.IGNORECASE)
_TEACHING_RE = re.compile(r"\b(teach me|as if teaching|like a teacher|tutor me|علمني|كأنك معلم|بأسلوب تعليمي)\b", re.IGNORECASE)

STYLE_INSTRUCTIONS = {
    "bullet_points": "Format the answer as a bullet-point list, one point per line, no long paragraphs.",
    "comparison": "Structure the answer as a direct side-by-side comparison — what's similar, what differs — rather than two separate descriptions.",
    "study_notes": "Format as structured study notes: short headings, concise bullet points under each, definitions bolded or clearly marked.",
    "exam_prep": "Format as exam-preparation material: key facts and definitions likely to be tested, phrased as concise, memorable statements.",
    "detailed": "Give a thorough, comprehensive answer — cover relevant nuance and don't skip steps in the reasoning.",
    "academic": "Use precise, formal, academic language — define terms rigorously, avoid colloquialisms, and structure the answer the way a textbook or paper would.",
    "teaching": "Explain the way a patient teacher would in a one-on-one lesson — build up from foundational ideas, check understanding of each piece before moving to the next, and use a concrete example.",
    "simple": None,  # no extra instruction — the base prompt's default behavior already covers this
}


def classify_answer_style(question: str) -> str:
    """Returns one of: 'bullet_points', 'comparison', 'study_notes',
    'exam_prep', 'academic', 'teaching', 'detailed', 'simple'. Checked in
    this order because a question can technically match more than one
    pattern (e.g. "compare X and Y in bullet points") — the more specific
    structural request (comparison) should win over a generic formatting
    note (bullets)."""
    if _COMPARISON_RE.search(question):
        return "comparison"
    if _STUDY_NOTES_RE.search(question):
        return "study_notes"
    if _EXAM_PREP_RE.search(question):
        return "exam_prep"
    if _TEACHING_RE.search(question):
        return "teaching"
    if _ACADEMIC_RE.search(question):
        return "academic"
    if _BULLET_RE.search(question):
        return "bullet_points"
    if _DETAILED_RE.search(question):
        return "detailed"
    return "simple"

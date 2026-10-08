import re

from ..domain.interfaces import LLMService
from .context_expander import expand_with_neighbors  # noqa: F401 — re-exported for backward compatibility;

# moved to context_expander.py in Phase 3 (dedicated retrieval-layer
# files per module responsibility). Anything importing
# `query_understanding.expand_with_neighbors` (there was nothing besides
# retriever.py, which now imports it directly from context_expander.py)
# keeps working unchanged.

# "Explain"-type questions need a teacher-style, more thorough answer with
# more supporting context than a quick fact lookup does.
# Includes both English and Arabic phrasing — the underlying embedding
# search and the LLM itself are already multilingual, but these are plain
# keyword regexes, which only match the language they're written for
# unless both are listed explicitly.
EXPLAIN_PATTERN = re.compile(
    r"\b(explain|why (?:is|does|do|did)|how does|how do|what'?s the difference|"
    r"elaborate|walk me through|teach me|what does .+ mean|help me understand|"
    r"what is the (?:purpose|significance|point) of|"
    r"اشرح|فسّر|فسر|وضّح|وضح|لماذا|ليش|كيف يعمل|كيف تعمل|ما الفرق|ما هو الفرق|"
    r"علّمني|علمني|ساعدني (?:على )?أفهم|ما المقصود|ايش يعني|ماذا يعني)\b",
    re.IGNORECASE,
)

# A direct request for brevity or depth, stated outright in the message.
# This is the strongest signal there is — it always wins.
SHORT_HINT_PATTERN = re.compile(
    r"\b(briefly|brief|quick(?:ly)?|in short|one sentence|short answer|tl;?dr|"
    r"باختصار|بإيجاز|بايجاز|بشكل مختصر|بشكل موجز|جملة واحدة|إجابة قصيرة|اجابة قصيرة|"
    r"اختصر)\b",
    re.IGNORECASE,
)
LONG_HINT_PATTERN = re.compile(
    r"\b(in detail|detailed|thoroughly|comprehensive|in depth|elaborate|explain fully|"
    r"بالتفصيل|بتفصيل|بشكل مفصل|بشكل مفصّل|بعمق|باستفاضة|اشرح بالكامل|بكل التفاصيل)\b",
    re.IGNORECASE,
)

# Asking to adjust the PREVIOUS answer ("make that shorter", "go deeper") —
# a conversational refinement rather than a property of this new question
# in isolation. Just as strong a signal as an explicit hint.
REFINE_SHORTER_PATTERN = re.compile(
    r"\b(shorter|make (?:it|that) shorter|too long|less detail|less verbose|"
    r"condense|trim (?:it|that) down|cut (?:it|that) down|tldr this|"
    r"اجعلها اقصر|اجعلها أقصر|اختصرها|طويلة جدا|طويلة جدًا|قلل التفاصيل|لخصها اكثر)\b",
    re.IGNORECASE,
)
REFINE_LONGER_PATTERN = re.compile(
    r"\b(more detail|go deeper|dig deeper|expand on (?:that|this)|elaborate more|"
    r"say more|longer answer|more thorough|"
    r"اعطني تفاصيل اكثر|أعطني تفاصيل أكثر|وسّع|وسع|فصّل اكثر|فصل أكثر|اشرح اكثر|اشرح أكثر)\b",
    re.IGNORECASE,
)

# A question that opens like a yes/no or single-value lookup ("Is...",
# "Does...", "How many...") is, by its own grammar, asking for a direct
# answer — not an essay. This is what lets the backend skip a UI toggle
# entirely and still default sensibly, the way ChatGPT does.
SIMPLE_FACT_PATTERN = re.compile(
    r"^(is|are|does|do|did|can|could|will|would|was|were|has|have|who|when|"
    r"where|how many|how much|what year|what date|"
    r"هل|متى|أين|وين|كم|من هو|من هي|ما هو|ما هي|أي)\b",
    re.IGNORECASE,
)


def classify_intent(question: str) -> str:
    """Fast, free, regex-based classification for 'does this need a fuller,
    more explanatory answer'. Kept deliberately separate from the
    summary/page/chapter detection that already lives in messages.py."""
    return "explain" if EXPLAIN_PATTERN.search(question) else "specific"


def _explicit_length_signal(question: str) -> str | None:
    """Checks the strongest, least ambiguous signals first: the user
    saying outright what they want, either about this question or as a
    refinement of the answer they just got."""
    if SHORT_HINT_PATTERN.search(question):
        return "short"
    if LONG_HINT_PATTERN.search(question):
        return "long"
    if REFINE_SHORTER_PATTERN.search(question):
        return "short"
    if REFINE_LONGER_PATTERN.search(question):
        return "long"
    return None


def infer_response_length(question: str, intent: str | None = None) -> str:
    """Decides 'short' | 'long' | 'auto' from the message alone — no UI
    toggle involved. Priority order:
    1. An explicit phrase in THIS message ('briefly', 'in detail'...).
    2. A refinement of the previous answer ('make that shorter'...).
    3. The question's own shape: a yes/no or single-fact lookup defaults
       short; an explanatory/conceptual question defaults long.
    4. Otherwise 'auto' — the model uses its own judgment per question,
       same as rule 5 in the system prompt handles it either way.
    """
    explicit = _explicit_length_signal(question)
    if explicit:
        return explicit

    if intent == "explain":
        return "long"

    if intent == "specific":
        stripped = question.strip()
        looks_like_simple_fact = (
            SIMPLE_FACT_PATTERN.match(stripped)
            and stripped.count("?") <= 1
            and " and " not in stripped.lower()
        )
        if looks_like_simple_fact:
            return "short"

    return "auto"


def rewrite_standalone_query(question: str, history: list[dict], llm_service: LLMService) -> str:
    """Turns a possibly context-dependent follow-up ('what about the
    second one?', 'why is that important?') into a fully self-contained
    search query, using recent conversation turns to resolve the
    reference. This is what actually makes multi-turn conversations work
    with embedding search — without it, a follow-up question searches on
    its own words alone and usually retrieves the wrong passage.

    Falls back to the original question on any failure or if there's no
    history yet (first message in the chat).
    """
    if not history:
        return question

    recent = history[-6:]
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in recent)

    try:
        rewritten = llm_service.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the user's new question into a fully self-contained "
                        "search query for a document search engine, resolving any "
                        "pronouns or references to earlier turns using the "
                        "conversation so far (e.g. 'that', 'the second one', 'it'). "
                        "Output ONLY the rewritten query, no commentary or quotes. "
                        "If the question is already self-contained, return it "
                        "unchanged."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Conversation so far:\n{transcript}\n\nNew question: {question}",
                },
            ],
            temperature=0,
        )
        rewritten = rewritten.strip().strip('"')
        return rewritten or question
    except Exception:
        return question


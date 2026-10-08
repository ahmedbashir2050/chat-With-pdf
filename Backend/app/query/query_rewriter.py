"""Query rewriting (spec item 4). `retrieval.query_understanding.
rewrite_standalone_query` already does this — LLM-based, resolves
pronouns/references against recent conversation turns, falls back to the
original question on any failure or when there's no history. This
module is a thin named wrapper, not a reimplementation: Phase 6's brief
says "integrate with... Conversation Memory", and duplicating an
LLM-prompted rewrite would risk the two drifting into inconsistent
behavior for the exact same job.
"""

from ..domain.interfaces import LLMService
from ..retrieval.query_understanding import rewrite_standalone_query


def rewrite_query(question: str, history: list[dict], llm_service: LLMService) -> str:
    return rewrite_standalone_query(question, history, llm_service)

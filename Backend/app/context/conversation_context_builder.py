"""ConversationContextBuilder (spec item 9). Follow-up resolution
("its disadvantages" -> "machine learning's disadvantages") already
exists — `retrieval/query_understanding.rewrite_standalone_query`, used
by `Retriever` since Phase 3 — and Phase 5's instructions say "Keep
Hybrid Search and Reranking unchanged", which that function is part of.
This class doesn't reimplement it; it composes it with message-history
retrieval into the single object the rest of the context layer works
with, so callers get one `ConversationContext` instead of separately
fetching history and rewriting the query.
"""

from dataclasses import dataclass

from ..domain.interfaces import LLMService, MessageRepository
from ..retrieval.query_understanding import rewrite_standalone_query


@dataclass
class ConversationContext:
    history: list[dict]
    standalone_query: str  # the follow-up resolved to a self-contained query, e.g. "its" -> "machine learning"


class ConversationContextBuilder:
    def __init__(self, message_repo: MessageRepository, llm_service: LLMService, history_window: int = 6):
        self._messages = message_repo
        self._llm = llm_service
        self._history_window = history_window

    def build(self, chat_id: int, question: str) -> ConversationContext:
        history = self._messages.get_recent(chat_id, self._history_window)
        standalone_query = rewrite_standalone_query(question, history, self._llm)
        return ConversationContext(history=history, standalone_query=standalone_query)

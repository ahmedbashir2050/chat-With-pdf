"""Chat lifecycle use cases. This absorbs what used to be directly inside
routers/chats.py — the router is now a thin adapter that parses the
upload, calls one of these methods, and maps the result to a response
schema.
"""

from ..domain.interfaces import ChatRepository, ChunkRepository, DocumentParser, EmbeddingService
from ..retrieval.keyword_search import KeywordIndexCache
from .summarization_service import SummarizationService


class ChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        chunk_repo: ChunkRepository,
        document_parser: DocumentParser,
        embedding_service: EmbeddingService,
        summarization_service: SummarizationService,
        keyword_index_cache: KeywordIndexCache,
    ):
        self._chats = chat_repo
        self._chunks = chunk_repo
        self._parser = document_parser
        self._embeddings = embedding_service
        self._summarizer = summarization_service
        self._keyword_index_cache = keyword_index_cache

    def create_chat(self, user_id: int, filename: str, pdf_bytes: bytes):
        title = filename.rsplit(".", 1)[0]
        chat = self._chats.create(user_id=user_id, title=title, pdf_name=filename)

        new_chunks = self._process_pdf(chat.id, pdf_bytes)
        self._chunks.save_many(new_chunks)  # backfills chunk.id on each item in new_chunks
        self._keyword_index_cache.get_or_build(chat.id, new_chunks)
        chat.overview = self._summarizer.generate_overview(new_chunks)

        self._chats.commit()
        self._chats.refresh(chat)
        return chat

    def list_chats(self, user_id: int):
        return self._chats.list_for_user(user_id)

    def delete_chat(self, chat_id: int, user_id: int) -> bool:
        chat = self._chats.get_owned_or_none(chat_id, user_id)
        if not chat:
            return False
        self._chats.delete(chat)
        self._chats.commit()
        self._keyword_index_cache.invalidate(chat_id)
        return True

    def replace_resource(self, chat_id: int, user_id: int, filename: str, pdf_bytes: bytes):
        chat = self._chats.get_owned_or_none(chat_id, user_id)
        if not chat:
            return None

        self._chunks.delete_for_chat(chat_id)
        new_chunks = self._process_pdf(chat_id, pdf_bytes)
        self._chunks.save_many(new_chunks)  # backfills chunk.id on each item in new_chunks
        self._keyword_index_cache.get_or_build(chat_id, new_chunks)

        chat.pdf_name = filename
        chat.overview = self._summarizer.generate_overview(new_chunks)
        self._chats.commit()
        self._chats.refresh(chat)
        return chat

    def get_owned_chat(self, chat_id: int, user_id: int):
        return self._chats.get_owned_or_none(chat_id, user_id)

    def _process_pdf(self, chat_id: int, pdf_bytes: bytes) -> list:
        chunks = self._parser.extract_chunks(pdf_bytes, chat_id=chat_id)
        if not chunks:
            raise ValueError("Couldn't extract any text from this PDF.")

        texts = [c.text for c in chunks]
        embeddings: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            embeddings.extend(self._embeddings.embed_batch(texts[i : i + batch_size]))

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        return chunks

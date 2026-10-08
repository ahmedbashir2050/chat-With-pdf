"""Repository implementations wrapping SQLAlchemy. This is what routers
used to do directly (`db.query(models.Chunk)...` scattered through
routers/chats.py and routers/messages.py in the original layout) — now
isolated here so application-layer services depend on repository
*interfaces*, not on SQLAlchemy query syntax.

Chat/User/Message repositories return SQLAlchemy model instances directly
(Pydantic's `from_attributes=True` schemas already read those natively,
so there's no value in wrapping them in a parallel domain type yet).
ChunkRepository is the exception: it converts to/from the domain
DocumentChunk dataclass, since chunks are what actually flow through
parsing → embedding → retrieval → prompting, where framework-agnostic
types matter.
"""

import json

from sqlalchemy.orm import Session

from .. import models
from ..domain.entities import DocumentChunk


class SqlAlchemyChatRepository:
    """Implements domain.interfaces.ChatRepository."""

    def __init__(self, db: Session):
        self._db = db

    def get_owned_or_none(self, chat_id: int, user_id: int) -> models.Chat | None:
        return (
            self._db.query(models.Chat)
            .filter(models.Chat.id == chat_id, models.Chat.user_id == user_id)
            .first()
        )

    def create(self, user_id: int, title: str, pdf_name: str) -> models.Chat:
        chat = models.Chat(user_id=user_id, title=title, pdf_name=pdf_name)
        self._db.add(chat)
        self._db.flush()  # assigns chat.id before chunks are attached
        return chat

    def list_for_user(self, user_id: int) -> list[models.Chat]:
        return (
            self._db.query(models.Chat)
            .filter(models.Chat.user_id == user_id)
            .order_by(models.Chat.id.desc())
            .all()
        )

    def delete(self, chat: models.Chat) -> None:
        self._db.delete(chat)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, chat: models.Chat) -> None:
        self._db.refresh(chat)


class SqlAlchemyChunkRepository:
    """Implements domain.interfaces.ChunkRepository."""

    def __init__(self, db: Session):
        self._db = db

    def save_many(self, chunks: list[DocumentChunk]) -> None:
        rows = []
        for c in chunks:
            extra = {}
            if c.bbox is not None:
                extra["bbox"] = list(c.bbox)
            if c.previous_chunk_id is not None:
                extra["previous_chunk_id"] = c.previous_chunk_id
            if c.next_chunk_id is not None:
                extra["next_chunk_id"] = c.next_chunk_id
            if c.quality_status is not None:
                extra["quality_status"] = c.quality_status
            if c.source_type is not None:
                extra["source_type"] = c.source_type
            if c.page_classification is not None:
                extra["page_classification"] = c.page_classification
            if c.quality_score is not None:
                extra["quality_score"] = c.quality_score

            row = models.Chunk(
                chat_id=c.chat_id,
                page=c.page,
                page_label=c.page_label,
                text=c.text,
                embedding=json.dumps(c.embedding),
                document_id=c.document_id,
                chapter=c.chapter,
                section=c.section,
                subsection=c.subsection,
                heading=c.heading,
                paragraph_index=c.paragraph_index,
                language=c.language,
                word_count=c.word_count,
                chunk_type=c.chunk_type,
                extra_metadata=json.dumps(extra) if extra else None,
            )
            self._db.add(row)
            rows.append(row)

        # Flush (not commit — the caller controls the transaction
        # boundary) so autoincrement ids are assigned, then backfill them
        # onto the input DocumentChunk objects. Without this, `chunks`
        # would still have id=None right after save_many returns, which
        # is exactly the state the Phase 3 keyword-index warm-up
        # (ChatService._process_pdf's caller) needs populated to build a
        # usable index immediately rather than waiting for the next
        # `get_for_chat` round-trip.
        self._db.flush()
        for c, row in zip(chunks, rows):
            c.id = row.id

    def delete_for_chat(self, chat_id: int) -> None:
        self._db.query(models.Chunk).filter(models.Chunk.chat_id == chat_id).delete()

    def get_for_chat(self, chat_id: int) -> list[DocumentChunk]:
        rows = (
            self._db.query(models.Chunk)
            .filter(models.Chunk.chat_id == chat_id)
            .order_by(models.Chunk.page)
            .all()
        )
        return [self._to_domain(r) for r in rows]

    @staticmethod
    def _to_domain(r: models.Chunk) -> DocumentChunk:
        extra = json.loads(r.extra_metadata) if r.extra_metadata else {}
        bbox = tuple(extra["bbox"]) if "bbox" in extra else None
        return DocumentChunk(
            id=r.id,
            chat_id=r.chat_id,
            page=r.page,
            page_label=r.page_label,
            text=r.text,
            embedding=json.loads(r.embedding),
            document_id=r.document_id,
            chapter=r.chapter,
            section=r.section,
            subsection=r.subsection,
            heading=r.heading,
            paragraph_index=r.paragraph_index,
            bbox=bbox,
            language=r.language,
            word_count=r.word_count,
            previous_chunk_id=extra.get("previous_chunk_id"),
            next_chunk_id=extra.get("next_chunk_id"),
            chunk_type=r.chunk_type,
            quality_status=extra.get("quality_status"),
            source_type=extra.get("source_type"),
            page_classification=extra.get("page_classification"),
            quality_score=extra.get("quality_score"),
        )


class SqlAlchemyMessageRepository:
    """Implements domain.interfaces.MessageRepository."""

    def __init__(self, db: Session):
        self._db = db

    def add(self, chat_id: int, role: str, content: str) -> None:
        self._db.add(models.Message(chat_id=chat_id, role=role, content=content))

    def get_recent(self, chat_id: int, limit: int) -> list[dict]:
        rows = (
            self._db.query(models.Message)
            .filter(models.Message.chat_id == chat_id)
            .order_by(models.Message.id)
            .all()
        )
        return [{"role": m.role, "content": m.content} for m in rows[-limit:]]

    def get_all_for_chat(self, chat_id: int) -> list[models.Message]:
        return (
            self._db.query(models.Message)
            .filter(models.Message.chat_id == chat_id)
            .order_by(models.Message.id)
            .all()
        )


class SqlAlchemyUserRepository:
    """Implements domain.interfaces.UserRepository."""

    def __init__(self, db: Session):
        self._db = db

    def get_by_google_sub(self, google_sub: str) -> models.User | None:
        return self._db.query(models.User).filter(models.User.google_sub == google_sub).first()

    def get_by_id(self, user_id: int) -> models.User | None:
        return self._db.query(models.User).filter(models.User.id == user_id).first()

    def create(self, google_sub: str, email: str, name: str | None, picture_url: str | None) -> models.User:
        user = models.User(google_sub=google_sub, email=email, name=name, picture_url=picture_url)
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user

    def update_profile(self, user: models.User, email: str, name: str | None, picture_url: str | None) -> None:
        user.email = email
        user.name = name
        user.picture_url = picture_url
        self._db.commit()

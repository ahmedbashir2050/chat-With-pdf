from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_sub = Column(String, unique=True, nullable=False, index=True)  # Google's stable user id
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    picture_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    chats = relationship("Chat", back_populates="owner", cascade="all, delete-orphan")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    pdf_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Short auto-generated "what this document covers" blurb — generated
    # once at upload time and reused whenever a question falls outside the
    # document's scope, so the user gets a helpful redirect instead of a
    # bare "not found".
    overview = Column(Text, nullable=True)

    owner = relationship("User", back_populates="chats")
    messages = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan"
    )
    chunks = relationship(
        "Chunk", back_populates="chat", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    role = Column(String, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    chat = relationship("Chat", back_populates="messages")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    page = Column(Integer, nullable=False)  # physical PDF page index (1-based) — reliable for ordering/range logic
    page_label = Column(String, nullable=True)  # printed page label if detected (e.g. "12", "iv", "ج") — stored as
    # document metadata only; NOT used for citations, which are always built from the physical page (see domain/citations.py)
    text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=False)  # JSON-encoded list[float]

    # --- Phase 2: document intelligence metadata (all nullable — rows
    # from the pre-Phase-2 fixed-size chunker, or any future parser that
    # doesn't populate them, are still valid). Queryable/filterable
    # fields get real columns; positional data that's always read as a
    # unit (bbox, prev/next chunk linkage) is folded into one JSON
    # column rather than four more nullable columns nothing filters on.
    document_id = Column(String, nullable=True, index=True)
    chapter = Column(String, nullable=True)
    section = Column(String, nullable=True)
    subsection = Column(String, nullable=True)
    heading = Column(String, nullable=True)
    paragraph_index = Column(Integer, nullable=True)
    language = Column(String, nullable=True)
    word_count = Column(Integer, nullable=True)
    chunk_type = Column(String, nullable=True)
    extra_metadata = Column(Text, nullable=True)  # JSON: {bbox, previous_chunk_id, next_chunk_id}

    chat = relationship("Chat", back_populates="chunks")

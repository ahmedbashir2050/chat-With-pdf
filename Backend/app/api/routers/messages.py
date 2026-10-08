from fastapi import APIRouter, Depends, HTTPException

from ... import models, schemas
from ..deps import (
    get_chat_repository,
    get_chat_service,
    get_chunk_repository,
    get_current_user,
    get_message_repository,
    get_qa_service,
)

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])


@router.get("", response_model=list[schemas.MessageOut])
def list_messages(
    chat_id: int,
    current_user: models.User = Depends(get_current_user),
    chat_service=Depends(get_chat_service),
    message_repo=Depends(get_message_repository),
):
    if not chat_service.get_owned_chat(chat_id, current_user.id):
        raise HTTPException(404, "Chat not found.")
    return message_repo.get_all_for_chat(chat_id)


@router.post("", response_model=schemas.SendMessageResponse)
def send_message(
    chat_id: int,
    body: schemas.SendMessageRequest,
    current_user: models.User = Depends(get_current_user),
    chat_service=Depends(get_chat_service),
    chunk_repo=Depends(get_chunk_repository),
    chat_repo=Depends(get_chat_repository),
    qa_service=Depends(get_qa_service),
):
    chat = chat_service.get_owned_chat(chat_id, current_user.id)
    if not chat:
        raise HTTPException(404, "Chat not found.")

    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Question can't be empty.")

    all_chunks = chunk_repo.get_for_chat(chat_id)
    if not all_chunks:
        raise HTTPException(400, "This chat has no processed document yet.")

    result = qa_service.answer(chat_id, question, all_chunks, chat)

    # Commits the whole request's unit of work: the two new Message rows
    # added inside qa_service.answer(), plus a possibly-updated
    # chat.overview — all on the same SQLAlchemy session, so one commit
    # here is sufficient regardless of which repository "added" what.
    chat_repo.commit()

    citations = [
        schemas.CitationOut(
            document_id=c.document_id,
            physical_page=c.physical_page,
            chapter=c.chapter,
            section=c.section,
            heading=c.heading,
            bbox=list(c.bbox) if c.bbox else None,
        )
        for c in result.citations
    ]

    return {
        "reply": result.reply,
        "answer": result.reply,
        "citations": citations,
        "used_chunks": result.used_chunks,
        "confidence_score": result.confidence_score,
        "retrieval_score": result.retrieval_score,
        "evidence_coverage": result.evidence_coverage,
        "citation_score": result.citation_score,
        "grounding_score": result.grounding_score,
    }

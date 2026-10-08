from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ... import models, schemas
from ..deps import get_chat_service, get_current_user

router = APIRouter(prefix="/chats", tags=["chats"])


def _validate_pdf(file: UploadFile) -> None:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")


@router.post("", response_model=schemas.ChatOut)
async def create_chat(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    chat_service=Depends(get_chat_service),
):
    _validate_pdf(file)
    pdf_bytes = await file.read()
    try:
        return chat_service.create_chat(current_user.id, file.filename, pdf_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=list[schemas.ChatOut])
def list_chats(current_user: models.User = Depends(get_current_user), chat_service=Depends(get_chat_service)):
    return chat_service.list_chats(current_user.id)


@router.delete("/{chat_id}")
def delete_chat(
    chat_id: int, current_user: models.User = Depends(get_current_user), chat_service=Depends(get_chat_service)
):
    if not chat_service.delete_chat(chat_id, current_user.id):
        raise HTTPException(404, "Chat not found.")
    return {"ok": True}


@router.put("/{chat_id}/resource", response_model=schemas.ChatOut)
async def replace_resource(
    chat_id: int,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    chat_service=Depends(get_chat_service),
):
    _validate_pdf(file)
    pdf_bytes = await file.read()
    try:
        chat = chat_service.replace_resource(chat_id, current_user.id, file.filename, pdf_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not chat:
        raise HTTPException(404, "Chat not found.")
    return chat

from fastapi import APIRouter, Depends

from ... import models, schemas
from ..deps import get_auth_service, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=schemas.AuthResponse)
def google_sign_in(body: schemas.GoogleAuthRequest, auth_service=Depends(get_auth_service)):
    token, user = auth_service.sign_in_with_google(body.id_token)
    return schemas.AuthResponse(access_token=token, user=user)


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user

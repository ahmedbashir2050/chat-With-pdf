"""Auth use case — verifying a Google ID token and issuing our own
session. Absorbs what used to be directly inside routers/auth.py.
"""

from ..domain.interfaces import UserRepository
from ..security.tokens import TokenService


class AuthService:
    def __init__(self, token_service: TokenService, user_repo: UserRepository):
        self._tokens = token_service
        self._users = user_repo

    def sign_in_with_google(self, id_token: str) -> tuple[str, object]:
        """Returns (session_token, user)."""
        claims = self._tokens.verify_google_id_token(id_token)

        google_sub = claims["sub"]
        email = claims.get("email")
        name = claims.get("name")
        picture_url = claims.get("picture")

        user = self._users.get_by_google_sub(google_sub)
        if user is None:
            user = self._users.create(google_sub=google_sub, email=email, name=name, picture_url=picture_url)
        else:
            self._users.update_profile(user, email=email, name=name, picture_url=picture_url)

        token = self._tokens.create_access_token(user.id)
        return token, user

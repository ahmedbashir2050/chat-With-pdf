"""Token handling — Google ID token verification and our own session JWTs.
Behavior unchanged from the original auth.py; the only structural change
is reading configuration from an injected Settings object instead of
`os.environ[...]` at import time (Phase 1 finding §3.5)."""

from datetime import datetime, timedelta

from fastapi import HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt

from ..config import Settings

_google_request = google_requests.Request()


class TokenService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def verify_google_id_token(self, token: str) -> dict:
        """Verifies a Google-issued ID token and returns its claims. The
        audience check (against our client ID) is what stops someone
        handing us a token meant for a different application."""
        try:
            claims = id_token.verify_oauth2_token(token, _google_request, self._settings.google_client_id)
        except ValueError as e:
            raise HTTPException(401, f"Invalid Google ID token: {e}")

        if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise HTTPException(401, "Invalid token issuer.")

        return claims

    def create_access_token(self, user_id: int) -> str:
        """Issues OUR OWN session token. We don't make the client keep
        reusing the raw Google ID token for every API call — those expire
        in ~1 hour and aren't meant to be used that way."""
        expire = datetime.utcnow() + timedelta(days=self._settings.jwt_expire_days)
        payload = {"sub": str(user_id), "exp": expire}
        return jwt.encode(payload, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm)

    def decode_access_token(self, token: str) -> int:
        try:
            payload = jwt.decode(token, self._settings.jwt_secret, algorithms=[self._settings.jwt_algorithm])
            return int(payload["sub"])
        except (JWTError, KeyError, ValueError):
            raise HTTPException(401, "Invalid or expired session. Please sign in again.")

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
from pydantic import BaseModel

from app.config import get_settings


class SessionPayload(BaseModel):
    """Session data stored in JWT."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: int  # Milliseconds since epoch
    token_type: Optional[str] = None
    scope: Optional[str] = None
    id_token: Optional[str] = None


SESSION_EXPIRY_DAYS = 30


def create_session_token(payload: SessionPayload) -> str:
    """Create a signed JWT session token.

    Args:
        payload: Session data to encode

    Returns:
        Signed JWT string
    """
    settings = get_settings()

    data = payload.model_dump()
    data["iat"] = datetime.now(timezone.utc)
    data["exp"] = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRY_DAYS)

    return jwt.encode(data, settings.session_secret, algorithm="HS256")


def verify_session_token(token: str) -> Optional[SessionPayload]:
    """Verify and decode a session JWT.

    Args:
        token: JWT string to verify

    Returns:
        Decoded SessionPayload or None if invalid/expired
    """
    settings = get_settings()

    try:
        data = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
        return SessionPayload(**data)
    except JWTError:
        return None

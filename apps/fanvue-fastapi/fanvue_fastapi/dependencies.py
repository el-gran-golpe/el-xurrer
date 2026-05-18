from typing import Optional

from fastapi import Request, HTTPException

from fanvue_fastapi.session import verify_session_token, SessionPayload


def get_session_from_cookie(request: Request) -> Optional[SessionPayload]:
    """Extract and verify session from cookie.

    Args:
        request: FastAPI request object

    Returns:
        SessionPayload if valid session exists, None otherwise
    """
    from fanvue_fastapi.config import get_settings

    settings = get_settings()

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None

    return verify_session_token(token)


def require_session(request: Request) -> SessionPayload:
    """Dependency that requires a valid session.

    Raises:
        HTTPException: 401 if no valid session
    """
    session = get_session_from_cookie(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session

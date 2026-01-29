from datetime import datetime, timezone
from typing import Any, Optional, Tuple, Dict

import httpx

from app.config import get_settings
from app.oauth import refresh_access_token, OAuthError
from app.session import SessionPayload

# Refresh token 30 seconds before expiry
TOKEN_REFRESH_BUFFER_MS = 30_000


async def get_current_user(
    session: SessionPayload,
) -> Tuple[Optional[Dict[str, Any]], Optional[SessionPayload]]:
    """Fetch current user from Fanvue API with auto token refresh.

    Args:
        session: Current session with tokens

    Returns:
        Tuple of (user_data, updated_session).
        updated_session is None if no refresh was needed.
        user_data is None if the request failed.
    """
    settings = get_settings()
    updated_session: Optional[SessionPayload] = None
    access_token = session.access_token

    # Check if token needs refresh (expired or expiring within buffer)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if now_ms >= session.expires_at - TOKEN_REFRESH_BUFFER_MS and session.refresh_token:
        try:
            refreshed = await refresh_access_token(session.refresh_token)
            access_token = refreshed.get("access_token", session.access_token)
            updated_session = SessionPayload(
                access_token=access_token,
                refresh_token=refreshed.get("refresh_token", session.refresh_token),
                token_type=refreshed.get("token_type", session.token_type),
                scope=refreshed.get("scope", session.scope),
                id_token=refreshed.get("id_token", session.id_token),
                expires_at=now_ms + refreshed.get("expires_in", 0) * 1000,
            )
        except OAuthError:
            # Silently fail refresh, try with old token
            pass

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_base_url}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            return None, updated_session

        return response.json(), updated_session
    except Exception:
        return None, updated_session

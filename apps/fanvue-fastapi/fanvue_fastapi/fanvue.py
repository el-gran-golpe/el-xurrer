from datetime import datetime, timezone
from typing import Any, Optional, Tuple, Dict

import httpx

from fanvue_fastapi.config import get_settings
from fanvue_fastapi.oauth import refresh_access_token, OAuthError
from fanvue_fastapi.session import SessionPayload

# Refresh token 30 seconds before expiry
TOKEN_REFRESH_BUFFER_MS = 30_000


async def ensure_valid_token(
    session: SessionPayload,
) -> Tuple[str, Optional[SessionPayload]]:
    """Ensure access token is valid, refreshing if needed."""
    from fanvue_fastapi.config import (
        ProfileNotConfiguredError,
        get_profile_oauth_settings,
    )

    updated_session: Optional[SessionPayload] = None
    access_token = session.access_token

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    needs_refresh = (
        now_ms >= session.expires_at - TOKEN_REFRESH_BUFFER_MS
        and session.refresh_token is not None
    )
    if not needs_refresh:
        return access_token, None

    if not session.profile:
        return access_token, None

    try:
        profile_oauth = get_profile_oauth_settings(session.profile)
    except ProfileNotConfiguredError:
        return access_token, None

    try:
        refreshed = await refresh_access_token(
            session.refresh_token,  # type: ignore[arg-type]
            client_id=profile_oauth.client_id,
            client_secret=profile_oauth.client_secret,
        )
        access_token = refreshed.get("access_token", session.access_token)
        updated_session = SessionPayload(
            access_token=access_token,
            refresh_token=refreshed.get("refresh_token", session.refresh_token),
            token_type=refreshed.get("token_type", session.token_type),
            scope=refreshed.get("scope", session.scope),
            id_token=refreshed.get("id_token", session.id_token),
            expires_at=now_ms + refreshed.get("expires_in", 0) * 1000,
            profile=session.profile,
        )
    except OAuthError:
        pass

    return access_token, updated_session


async def get_current_user(
    session: SessionPayload,
) -> Tuple[Optional[Dict[str, Any]], Optional[SessionPayload]]:
    """Fetch current user from Fanvue API with auto token refresh."""
    settings = get_settings()
    access_token, updated_session = await ensure_valid_token(session)

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

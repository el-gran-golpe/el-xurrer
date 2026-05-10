import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from fanvue_fastapi.config import (
    ProfileNotConfiguredError,
    get_profile_oauth_settings,
    get_settings,
)
from fanvue_fastapi.oauth import (
    OAuthError,
    exchange_code_for_token,
    generate_pkce,
    get_authorize_url,
)
from fanvue_fastapi.session import SessionPayload, create_session_token

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

OAUTH_COOKIE_MAX_AGE = 600  # 10 minutes
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@router.get("/login")
async def login(request: Request, profile: str) -> Response:
    """Initiate OAuth login flow for a specific profile."""
    try:
        profile_oauth = get_profile_oauth_settings(profile)
    except ProfileNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pkce = generate_pkce()
    state = f"{profile}_{uuid.uuid4()}"

    auth_url = get_authorize_url(
        state=state,
        code_challenge=pkce["challenge"],
        client_id=profile_oauth.client_id,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    secure = request.url.scheme == "https"

    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=OAUTH_COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key="oauth_verifier",
        value=pkce["verifier"],
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=OAUTH_COOKIE_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key="oauth_profile",
        value=profile,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=OAUTH_COOKIE_MAX_AGE,
        path="/",
    )

    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> Response:
    """Handle OAuth callback from Fanvue."""
    settings = get_settings()

    stored_state = request.cookies.get("oauth_state")
    verifier = request.cookies.get("oauth_verifier")
    profile = request.cookies.get("oauth_profile")

    def make_redirect(path: str) -> RedirectResponse:
        response = RedirectResponse(url=f"{settings.base_url}{path}", status_code=302)
        response.delete_cookie("oauth_state", path="/")
        response.delete_cookie("oauth_verifier", path="/")
        response.delete_cookie("oauth_profile", path="/")
        return response

    if error:
        params = f"?error={error}"
        if error_description:
            params += f"&error_description={error_description}"
        return make_redirect(f"/{params}")

    if (
        not code
        or not state
        or not stored_state
        or not verifier
        or not profile
        or state != stored_state
    ):
        return make_redirect("/?error=oauth_state_mismatch")

    try:
        profile_oauth = get_profile_oauth_settings(profile)
    except ProfileNotConfiguredError:
        return make_redirect("/?error=profile_not_configured")

    try:
        token = await exchange_code_for_token(
            code=code,
            code_verifier=verifier,
            client_id=profile_oauth.client_id,
            client_secret=profile_oauth.client_secret,
        )
    except OAuthError:
        return make_redirect("/?error=oauth_token_exchange_failed")

    import sys
    from pathlib import Path as PathLib

    project_root = PathLib(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from main_components.fanvue_auth import FanvueTokenManager

    manager = FanvueTokenManager(profile)
    manager.save_tokens(dict(token))

    session = SessionPayload(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_type=token.get("token_type"),
        scope=token.get("scope"),
        id_token=token.get("id_token"),
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        profile=profile,
    )
    session_token = create_session_token(session)

    response = HTMLResponse(
        content="""
        <html>
            <head><title>Authentication Successful</title></head>
            <body>
                <h1>✓ Authentication Successful</h1>
                <p>You can close this window and return to the CLI.</p>
                <script>setTimeout(() => window.close(), 2000);</script>
            </body>
        </html>
        """,
        status_code=200,
    )
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_COOKIE_MAX_AGE,
        path="/",
    )
    response.delete_cookie("oauth_state", path="/")
    response.delete_cookie("oauth_verifier", path="/")
    response.delete_cookie("oauth_profile", path="/")
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Clear session and logout."""
    settings = get_settings()

    response = RedirectResponse(url=f"{settings.base_url}/", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")

    return response

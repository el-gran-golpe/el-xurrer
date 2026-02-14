import uuid
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.oauth import (
    generate_pkce,
    get_authorize_url,
    exchange_code_for_token,
    OAuthError,
)
from app.session import create_session_token, SessionPayload

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

# Cookie settings
OAUTH_COOKIE_MAX_AGE = 600  # 10 minutes
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@router.get("/login")
async def login(request: Request, profile: Optional[str] = None) -> Response:
    """Initiate OAuth login flow."""

    # Generate PKCE and state
    pkce = generate_pkce()

    # If profile provided, include in state for CLI flow
    if profile:
        state = f"{profile}_{str(uuid.uuid4())}"
    else:
        state = str(uuid.uuid4())

    # Build auth URL
    auth_url = get_authorize_url(state=state, code_challenge=pkce["challenge"])

    # Create redirect response
    response = RedirectResponse(url=auth_url, status_code=302)

    # Determine if secure cookies
    secure = request.url.scheme == "https"

    # Store state and verifier in cookies
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

    # Store profile name in cookie if provided (for CLI flow)
    if profile:
        response.set_cookie(
            key="oauth_profile",
            value=profile,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=OAUTH_COOKIE_MAX_AGE,
            path="/",
        )

    # Security headers
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

    # Get stored values from cookies
    stored_state = request.cookies.get("oauth_state")
    verifier = request.cookies.get("oauth_verifier")
    profile = request.cookies.get("oauth_profile")  # NEW: Get profile from cookie

    # Build base redirect (always clear OAuth cookies)
    def make_redirect(path: str) -> RedirectResponse:
        response = RedirectResponse(url=f"{settings.base_url}{path}", status_code=302)
        response.delete_cookie("oauth_state", path="/")
        response.delete_cookie("oauth_verifier", path="/")
        response.delete_cookie("oauth_profile", path="/")  # NEW: Clear profile cookie
        return response

    # Handle provider errors
    if error:
        params = f"?error={error}"
        if error_description:
            params += f"&error_description={error_description}"
        return make_redirect(f"/{params}")

    # Validate state and required params
    if (
        not code
        or not state
        or not stored_state
        or not verifier
        or state != stored_state
    ):
        return make_redirect("/?error=oauth_state_mismatch")

    # Exchange code for token
    try:
        token = await exchange_code_for_token(code=code, code_verifier=verifier)
    except OAuthError:
        return make_redirect("/?error=oauth_token_exchange_failed")

    # NEW: If profile is provided (CLI flow), save tokens to profile directory
    if profile:
        import sys
        from pathlib import Path as PathLib

        # Add project root to path
        project_root = PathLib(__file__).parent.parent.parent.parent
        sys.path.insert(0, str(project_root))

        from main_components.fanvue_auth import FanvueTokenManager

        manager = FanvueTokenManager(profile)
        manager.save_tokens(dict(token))  # Convert TypedDict to dict for type safety

        # Return simple success page for CLI flow
        return HTMLResponse(
            content="""
            <html>
                <head><title>Authentication Successful</title></head>
                <body>
                    <h1>✓ Authentication Successful</h1>
                    <p>You can close this window and return to the CLI.</p>
                    <script>
                        setTimeout(() => window.close(), 2000);
                    </script>
                </body>
            </html>
            """,
            status_code=200,
        )

    # Original flow: Create session for web app
    import time

    session = SessionPayload(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_type=token.get("token_type"),
        scope=token.get("scope"),
        id_token=token.get("id_token"),
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
    )
    session_token = create_session_token(session)

    # Create response with session cookie
    response = make_redirect("/")
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

    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Clear session and logout."""
    settings = get_settings()

    response = RedirectResponse(url=f"{settings.base_url}/", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")

    return response

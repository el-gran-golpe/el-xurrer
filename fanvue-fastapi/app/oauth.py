import base64
import hashlib
import secrets
from typing import TypedDict
from urllib.parse import urlencode

import httpx

from app.config import get_settings

DEFAULT_SCOPES = "openid offline_access offline"


class OAuthError(Exception):
    """Raised when OAuth operations fail."""

    pass


class PKCEResult(TypedDict):
    verifier: str
    challenge: str
    method: str


class TokenResponse(TypedDict, total=False):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    scope: str
    id_token: str


def _base64url(data: bytes) -> str:
    """Encode bytes as base64url without padding."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce() -> PKCEResult:
    """Generate PKCE verifier and challenge.

    Returns:
        Dict with verifier, challenge, and method (S256)
    """
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return {"verifier": verifier, "challenge": challenge, "method": "S256"}


def get_authorize_url(
    state: str,
    code_challenge: str,
    redirect_uri: str | None = None,
) -> str:
    """Build the Fanvue OAuth authorization URL.

    Args:
        state: Random state for CSRF protection
        code_challenge: PKCE challenge
        redirect_uri: Optional override for redirect URI

    Returns:
        Full authorization URL to redirect user to
    """
    settings = get_settings()

    scopes = f"{DEFAULT_SCOPES} {settings.oauth_scopes}".strip()

    params = {
        "response_type": "code",
        "client_id": settings.oauth_client_id,
        "redirect_uri": redirect_uri or settings.oauth_redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    if settings.oauth_response_mode:
        params["response_mode"] = settings.oauth_response_mode
    if settings.oauth_prompt:
        params["prompt"] = settings.oauth_prompt

    return f"{settings.oauth_issuer_base_url}/oauth2/auth?{urlencode(params)}"


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
) -> TokenResponse:
    """Exchange authorization code for access token.

    Args:
        code: Authorization code from callback
        code_verifier: PKCE verifier used during authorization
        redirect_uri: Optional override for redirect URI

    Returns:
        Token response with access_token, refresh_token, expires_in, etc.

    Raises:
        OAuthError: If token exchange fails
    """
    settings = get_settings()

    # Build Basic auth header
    credentials = f"{settings.oauth_client_id}:{settings.oauth_client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or settings.oauth_redirect_uri,
        "client_id": settings.oauth_client_id,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.oauth_issuer_base_url}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic_auth}",
            },
            data=data,
        )

    if response.status_code != 200:
        raise OAuthError(
            f"Token exchange failed: {response.status_code} {response.text}"
        )

    return response.json()

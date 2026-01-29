import base64
import hashlib
import secrets
from typing import TypedDict
from urllib.parse import urlencode

from app.config import get_settings

DEFAULT_SCOPES = "openid offline_access offline"


class PKCEResult(TypedDict):
    verifier: str
    challenge: str
    method: str


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

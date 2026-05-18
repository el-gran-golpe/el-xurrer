import base64
import hashlib
import secrets
from typing import TypedDict
from urllib.parse import urlencode

import httpx


DEFAULT_SCOPES = "openid offline_access offline"


class OAuthError(Exception):
    """Raised when OAuth operations fail."""


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
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce() -> PKCEResult:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return {"verifier": verifier, "challenge": challenge, "method": "S256"}


def get_authorize_url(
    state: str,
    code_challenge: str,
    client_id: str,
    redirect_uri: str,
    issuer_base_url: str,
    *,
    scopes: str = "",
    response_mode: str | None = None,
    prompt: str | None = None,
) -> str:
    merged_scopes = f"{DEFAULT_SCOPES} {scopes}".strip()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": merged_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if response_mode:
        params["response_mode"] = response_mode
    if prompt:
        params["prompt"] = prompt

    return f"{issuer_base_url}/oauth2/auth?{urlencode(params)}"


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    issuer_base_url: str,
) -> TokenResponse:
    credentials = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{issuer_base_url}/oauth2/token",
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


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    issuer_base_url: str,
) -> TokenResponse:
    credentials = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{issuer_base_url}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic_auth}",
            },
            data=data,
        )

    if response.status_code != 200:
        raise OAuthError(
            f"Token refresh failed: {response.status_code} {response.text}"
        )
    return response.json()

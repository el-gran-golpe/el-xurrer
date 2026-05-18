from fanvue_api_client.oauth import (
    DEFAULT_SCOPES,
    OAuthError,
    PKCEResult,
    TokenResponse,
    generate_pkce,
)
from fanvue_api_client.oauth import (
    exchange_code_for_token as client_exchange_code_for_token,
)
from fanvue_api_client.oauth import get_authorize_url as client_get_authorize_url
from fanvue_api_client.oauth import refresh_access_token as client_refresh_access_token

from fanvue_fastapi.config import get_settings


__all__ = [
    "DEFAULT_SCOPES",
    "OAuthError",
    "PKCEResult",
    "TokenResponse",
    "exchange_code_for_token",
    "generate_pkce",
    "get_authorize_url",
    "refresh_access_token",
]


def get_authorize_url(
    state: str,
    code_challenge: str,
    client_id: str,
    redirect_uri: str | None = None,
    issuer_base_url: str | None = None,
) -> str:
    settings = get_settings()
    return client_get_authorize_url(
        state=state,
        code_challenge=code_challenge,
        client_id=client_id,
        redirect_uri=redirect_uri or settings.oauth_redirect_uri,
        issuer_base_url=issuer_base_url or settings.oauth_issuer_base_url,
        scopes=settings.oauth_scopes,
        response_mode=settings.oauth_response_mode,
        prompt=settings.oauth_prompt,
    )


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str | None = None,
    issuer_base_url: str | None = None,
) -> TokenResponse:
    settings = get_settings()
    return await client_exchange_code_for_token(
        code=code,
        code_verifier=code_verifier,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri or settings.oauth_redirect_uri,
        issuer_base_url=issuer_base_url or settings.oauth_issuer_base_url,
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    issuer_base_url: str | None = None,
) -> TokenResponse:
    settings = get_settings()
    return await client_refresh_access_token(
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        issuer_base_url=issuer_base_url or settings.oauth_issuer_base_url,
    )

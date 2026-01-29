import base64
import hashlib
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest


def test_generate_pkce_returns_verifier_and_challenge():
    """PKCE generation should return verifier, challenge, and method."""
    from app.oauth import generate_pkce

    result = generate_pkce()

    assert "verifier" in result
    assert "challenge" in result
    assert result["method"] == "S256"


def test_generate_pkce_challenge_is_sha256_of_verifier():
    """Challenge should be base64url(SHA256(verifier))."""
    from app.oauth import generate_pkce

    result = generate_pkce()
    verifier = result["verifier"]
    challenge = result["challenge"]

    # Manually compute expected challenge
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    assert challenge == expected


def test_generate_pkce_verifier_is_unique():
    """Each call should generate a unique verifier."""
    from app.oauth import generate_pkce

    result1 = generate_pkce()
    result2 = generate_pkce()

    assert result1["verifier"] != result2["verifier"]


def test_get_authorize_url_contains_required_params(monkeypatch):
    """Authorization URL should contain all required OAuth params."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("OAUTH_SCOPES", "read:self")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.oauth import get_authorize_url

    url = get_authorize_url(state="test_state", code_challenge="test_challenge")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.fanvue.com"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test_client"]
    assert params["state"] == ["test_state"]
    assert params["code_challenge"] == ["test_challenge"]
    assert params["code_challenge_method"] == ["S256"]
    assert "openid" in params["scope"][0]
    assert "offline_access" in params["scope"][0]
    assert "read:self" in params["scope"][0]


@pytest.mark.asyncio
async def test_exchange_code_for_token_success(monkeypatch):
    """Token exchange should return tokens on success."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    with patch("app.oauth.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = (
            mock_response
        )

        from app.oauth import exchange_code_for_token

        result = await exchange_code_for_token(
            code="test_code",
            code_verifier="test_verifier",
        )

    assert result["access_token"] == "test_access_token"
    assert result["refresh_token"] == "test_refresh_token"
    assert result["expires_in"] == 3600


@pytest.mark.asyncio
async def test_exchange_code_for_token_failure_raises(monkeypatch):
    """Token exchange should raise on HTTP error."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"

    with patch("app.oauth.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = (
            mock_response
        )

        from app.oauth import OAuthError, exchange_code_for_token

        with pytest.raises(OAuthError):
            await exchange_code_for_token(
                code="invalid_code",
                code_verifier="test_verifier",
            )

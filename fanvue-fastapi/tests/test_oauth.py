import base64
import hashlib
from urllib.parse import parse_qs, urlparse


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

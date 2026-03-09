from datetime import datetime, timedelta, timezone


def test_create_session_token(monkeypatch):
    """Create session should return a valid JWT."""
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    get_settings.cache_clear()

    from fanvue_fastapi.session import create_session_token, SessionPayload

    payload = SessionPayload(
        access_token="test_access",
        refresh_token="test_refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    token = create_session_token(payload)

    assert isinstance(token, str)
    assert len(token) > 0


def test_verify_session_token(monkeypatch):
    """Verify session should decode a valid JWT."""
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    get_settings.cache_clear()

    from fanvue_fastapi.session import (
        create_session_token,
        verify_session_token,
        SessionPayload,
    )

    original = SessionPayload(
        access_token="test_access",
        refresh_token="test_refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    token = create_session_token(original)
    decoded = verify_session_token(token)

    assert decoded is not None
    assert decoded.access_token == "test_access"
    assert decoded.refresh_token == "test_refresh"


def test_verify_session_token_returns_none_for_invalid(monkeypatch):
    """Verify session should return None for invalid JWT."""
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    get_settings.cache_clear()

    from fanvue_fastapi.session import verify_session_token

    result = verify_session_token("invalid.jwt.token")

    assert result is None

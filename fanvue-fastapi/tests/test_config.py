import pytest


def test_settings_loads_from_env(monkeypatch):
    """Settings should load all required env vars."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.oauth_client_id == "test_client_id"
    assert settings.oauth_client_secret == "test_client_secret"
    assert settings.session_secret == "test_session_secret_16"


def test_settings_validates_session_secret_length(monkeypatch):
    """SESSION_SECRET must be at least 16 characters."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "short")  # Too short
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    with pytest.raises(Exception):
        get_settings.cache_clear()
        get_settings()

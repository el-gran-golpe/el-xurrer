import pytest


def test_settings_loads_from_env(monkeypatch):
    """Settings should load all required env vars."""
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.oauth_redirect_uri == "http://localhost:8000/callback"
    assert settings.session_secret == "test_session_secret_16"
    assert settings.api_base_url == "https://api.fanvue.com"


def test_settings_validates_session_secret_length(monkeypatch):
    """SESSION_SECRET must be at least 16 characters."""
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "short")  # Too short
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    with pytest.raises(Exception):
        get_settings.cache_clear()
        get_settings()


def test_get_profile_oauth_settings_loads_per_profile_vars(monkeypatch):
    monkeypatch.setenv("FANVUE_WEBAPP_HARU_OAUTH_CLIENT_ID", "haru_id")
    monkeypatch.setenv("FANVUE_WEBAPP_HARU_OAUTH_CLIENT_SECRET", "haru_secret")
    monkeypatch.setenv("FANVUE_WEBAPP_CHARLY_OAUTH_CLIENT_ID", "charly_id")
    monkeypatch.setenv("FANVUE_WEBAPP_CHARLY_OAUTH_CLIENT_SECRET", "charly_secret")

    from fanvue_fastapi.config import get_profile_oauth_settings

    haru = get_profile_oauth_settings("haru")
    charly = get_profile_oauth_settings("charly")

    assert haru.client_id == "haru_id"
    assert haru.client_secret == "haru_secret"
    assert charly.client_id == "charly_id"
    assert charly.client_secret == "charly_secret"


def test_get_profile_oauth_settings_missing_profile_raises(monkeypatch):
    monkeypatch.delenv("FANVUE_WEBAPP_GHOST_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("FANVUE_WEBAPP_GHOST_OAUTH_CLIENT_SECRET", raising=False)

    from fanvue_fastapi.config import (
        get_profile_oauth_settings,
        ProfileNotConfiguredError,
    )

    with pytest.raises(ProfileNotConfiguredError, match="ghost"):
        get_profile_oauth_settings("ghost")


def test_get_profile_oauth_settings_normalizes_case(monkeypatch):
    monkeypatch.setenv("FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_ID", "lv_id")
    monkeypatch.setenv("FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_SECRET", "lv_secret")

    from fanvue_fastapi.config import get_profile_oauth_settings

    result = get_profile_oauth_settings("laura_vigne")

    assert result.client_id == "lv_id"

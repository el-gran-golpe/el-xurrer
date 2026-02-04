import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_get_current_user_returns_user_data(monkeypatch):
    """get_current_user should return user data from Fanvue API."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.session import SessionPayload

    # Session with valid (non-expired) token
    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh_token",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "123", "username": "testuser"}

    with patch("app.fanvue.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        from app.fanvue import get_current_user

        result, updated_session = await get_current_user(session)

        assert result is not None
        assert result["username"] == "testuser"
        assert updated_session is None


@pytest.mark.asyncio
async def test_get_current_user_refreshes_expired_token(monkeypatch):
    """get_current_user should refresh token if expired."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.session import SessionPayload

    # Session with expired token
    session = SessionPayload(
        access_token="expired_token",
        refresh_token="refresh_token",
        expires_at=int(
            (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    mock_user_response = MagicMock()
    mock_user_response.status_code = 200
    mock_user_response.json.return_value = {"id": "123", "username": "testuser"}

    with (
        patch("app.fanvue.refresh_access_token") as mock_refresh,
        patch("app.fanvue.httpx.AsyncClient") as mock_client,
    ):
        # Setup refresh mock
        mock_refresh.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        # Setup client mock to return user response
        mock_client.return_value.__aenter__.return_value.get.return_value = (
            mock_user_response
        )

        from app.fanvue import get_current_user

        result, updated_session = await get_current_user(session)

        assert result is not None
        assert result["username"] == "testuser"
        assert updated_session is not None
        assert updated_session.access_token == "new_access_token"
        assert updated_session.refresh_token == "new_refresh_token"


@pytest.mark.asyncio
async def test_ensure_valid_token_returns_original_when_not_expired(monkeypatch):
    """ensure_valid_token should return original token when not expired."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.session import SessionPayload

    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh_token",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    from app.fanvue import ensure_valid_token

    access_token, updated_session = await ensure_valid_token(session)

    assert access_token == "valid_token"
    assert updated_session is None


@pytest.mark.asyncio
async def test_ensure_valid_token_refreshes_when_expired(monkeypatch):
    """ensure_valid_token should refresh token when expired."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.session import SessionPayload

    session = SessionPayload(
        access_token="expired_token",
        refresh_token="refresh_token",
        expires_at=int(
            (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
        ),
        token_type="Bearer",
    )

    with patch("app.fanvue.refresh_access_token") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        from app.fanvue import ensure_valid_token

        access_token, updated_session = await ensure_valid_token(session)

        assert access_token == "new_access_token"
        assert updated_session is not None
        assert updated_session.access_token == "new_access_token"

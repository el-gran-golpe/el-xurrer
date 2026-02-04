import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client(monkeypatch):
    """Create test client with mocked settings."""
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")

    from app.config import get_settings

    get_settings.cache_clear()

    from main import app

    return TestClient(app)


def test_create_post_requires_authentication(client):
    """POST /api/posts should return 401 without session."""
    response = client.post("/api/posts", data={"text": "Hello"})
    assert response.status_code == 401


def test_create_post_requires_content(client, monkeypatch):
    """POST /api/posts should return 400 without text or files."""
    # Mock session verification to return valid session
    from app.session import SessionPayload
    from datetime import datetime, timezone, timedelta

    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
    )

    with patch("app.dependencies.verify_session_token", return_value=session):
        response = client.post(
            "/api/posts",
            data={},
            cookies={"fvsession": "mock_token"},
        )
        assert response.status_code == 400
        assert "text or files" in response.json()["detail"].lower()

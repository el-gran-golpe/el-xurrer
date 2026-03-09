import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client(monkeypatch):
    """Create test client with mocked settings."""
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

    from main import app

    return TestClient(app)


def test_create_post_requires_authentication(client):
    """POST /api/posts should return 401 without session."""
    response = client.post("/api/posts", data={"text": "Hello"})
    assert response.status_code == 401


def test_create_post_requires_content(client, monkeypatch):
    """POST /api/posts should return 400 without text or files."""
    # Mock session verification to return valid session
    from fanvue_fastapi.session import SessionPayload
    from datetime import datetime, timezone, timedelta

    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
    )

    with patch(
        "fanvue_fastapi.dependencies.verify_session_token", return_value=session
    ):
        response = client.post(
            "/api/posts",
            data={},
            cookies={"fvsession": "mock_token"},
        )
        assert response.status_code == 400
        assert "text or files" in response.json()["detail"].lower()


def test_create_post_with_text_success(client, monkeypatch):
    """POST /api/posts with text should create post successfully."""
    from fanvue_fastapi.session import SessionPayload
    from datetime import datetime, timezone, timedelta

    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
    )

    with (
        patch("fanvue_fastapi.dependencies.verify_session_token", return_value=session),
        patch(
            "fanvue_fastapi.routes.posts.ensure_valid_token",
            return_value=("valid_token", None),
        ),
        patch("fanvue_fastapi.routes.posts.create_post") as mock_create,
    ):
        mock_create.return_value = {
            "uuid": "post-123",
            "createdAt": "2024-03-15T10:00:00Z",
            "text": "Hello world",
            "audience": "subscribers",
        }

        response = client.post(
            "/api/posts",
            data={"text": "Hello world"},
            cookies={"fvsession": "mock_token"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["uuid"] == "post-123"
        assert data["text"] == "Hello world"
        assert data["uploadFailures"] == []


def test_create_post_with_file_and_text(client, monkeypatch):
    """POST /api/posts with file and text should upload media and create post."""
    from fanvue_fastapi.session import SessionPayload
    from datetime import datetime, timezone, timedelta
    from fanvue_fastapi.media import MediaUploadResult

    session = SessionPayload(
        access_token="valid_token",
        refresh_token="refresh",
        expires_at=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
    )

    with (
        patch("fanvue_fastapi.dependencies.verify_session_token", return_value=session),
        patch(
            "fanvue_fastapi.routes.posts.ensure_valid_token",
            return_value=("valid_token", None),
        ),
        patch("fanvue_fastapi.routes.posts.upload_media") as mock_upload,
        patch("fanvue_fastapi.routes.posts.create_post") as mock_create,
    ):
        mock_upload.return_value = MediaUploadResult(
            success=True,
            media_uuid="media-123",
            filename="test.jpg",
        )
        mock_create.return_value = {
            "uuid": "post-123",
            "createdAt": "2024-03-15T10:00:00Z",
            "text": "Check this out",
            "audience": "subscribers",
        }

        response = client.post(
            "/api/posts",
            data={"text": "Check this out"},
            files={"files": ("test.jpg", b"fake image data", "image/jpeg")},
            cookies={"fvsession": "mock_token"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["uuid"] == "post-123"
        assert data["mediaUuids"] == ["media-123"]
        mock_upload.assert_called_once()

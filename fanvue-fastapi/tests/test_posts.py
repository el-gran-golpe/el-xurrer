import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_create_post_sends_correct_payload(monkeypatch):
    """create_post should send correct payload to Fanvue API."""
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
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "uuid": "post-uuid",
        "createdAt": "2024-03-15T10:00:00Z",
        "text": "Hello world",
        "audience": "subscribers",
    }

    with patch("app.posts.httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value.__aenter__.return_value
        mock_instance.post.return_value = mock_response

        from app.posts import create_post

        result = await create_post(
            text="Hello world",
            media_uuids=["uuid-1"],
            audience="subscribers",
            publish_at=None,
            access_token="valid_token",
        )

        assert result["uuid"] == "post-uuid"

        # Verify correct payload
        call_kwargs = mock_instance.post.call_args[1]
        assert call_kwargs["json"]["text"] == "Hello world"
        assert call_kwargs["json"]["mediaUuids"] == ["uuid-1"]
        assert call_kwargs["json"]["audience"] == "subscribers"


@pytest.mark.asyncio
async def test_create_post_raises_on_error(monkeypatch):
    """create_post should raise PostCreationError on API error."""
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
    mock_response.text = "Bad request"

    with patch("app.posts.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = (
            mock_response
        )

        from app.posts import create_post, PostCreationError

        with pytest.raises(PostCreationError):
            await create_post(
                text="Hello",
                media_uuids=[],
                audience="subscribers",
                publish_at=None,
                access_token="valid_token",
            )

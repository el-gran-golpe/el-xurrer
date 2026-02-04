import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_initiate_upload_returns_upload_info(monkeypatch):
    """initiate_upload should return mediaUuid and uploadId."""
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
        "mediaUuid": "media-uuid-123",
        "uploadId": "upload-id-456",
    }

    with patch("app.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = (
            mock_response
        )

        from app.media import initiate_upload

        result = await initiate_upload(
            filename="test.jpg",
            content_type="image/jpeg",
            access_token="valid_token",
        )

        assert result["mediaUuid"] == "media-uuid-123"
        assert result["uploadId"] == "upload-id-456"


@pytest.mark.asyncio
async def test_get_upload_url_returns_signed_url(monkeypatch):
    """get_upload_url should return signed URL for chunk."""
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
    mock_response.json.return_value = {"url": "https://storage.example.com/signed-url"}

    with patch("app.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        from app.media import get_upload_url

        url = await get_upload_url(
            upload_id="upload-123",
            part_number=1,
            access_token="valid_token",
        )

        assert url == "https://storage.example.com/signed-url"


@pytest.mark.asyncio
async def test_upload_chunk_returns_etag(monkeypatch):
    """upload_chunk should return ETag from response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"ETag": '"abc123"'}

    with patch("app.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put.return_value = (
            mock_response
        )

        from app.media import upload_chunk

        etag = await upload_chunk(
            url="https://storage.example.com/signed-url",
            data=b"chunk data",
        )

        assert etag == '"abc123"'

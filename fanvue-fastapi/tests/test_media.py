from io import BytesIO

import pytest
from unittest.mock import MagicMock, patch
from fastapi import UploadFile


@pytest.mark.asyncio
async def test_initiate_upload_returns_upload_info(monkeypatch):
    """initiate_upload should return mediaUuid and uploadId."""
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

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "mediaUuid": "media-uuid-123",
        "uploadId": "upload-id-456",
    }

    with patch("fanvue_fastapi.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = (
            mock_response
        )

        from fanvue_fastapi.media import initiate_upload

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

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "https://storage.example.com/signed-url"

    with patch("fanvue_fastapi.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        from fanvue_fastapi.media import get_upload_url

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

    with patch("fanvue_fastapi.media.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put.return_value = (
            mock_response
        )

        from fanvue_fastapi.media import upload_chunk

        etag = await upload_chunk(
            url="https://storage.example.com/signed-url",
            data=b"chunk data",
        )

        assert etag == '"abc123"'


@pytest.mark.asyncio
async def test_complete_upload_sends_etags(monkeypatch):
    """complete_upload should send ETags to finalize upload."""
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

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("fanvue_fastapi.media.httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value.__aenter__.return_value
        mock_instance.patch.return_value = mock_response

        from fanvue_fastapi.media import complete_upload

        await complete_upload(
            upload_id="upload-123",
            etags=['"etag1"', '"etag2"'],
            access_token="valid_token",
        )

        # Verify PATCH was called with correct payload
        mock_instance.patch.assert_called_once()
        call_kwargs = mock_instance.patch.call_args[1]
        assert call_kwargs["json"]["parts"] == [
            {"PartNumber": 1, "ETag": '"etag1"'},
            {"PartNumber": 2, "ETag": '"etag2"'},
        ]


@pytest.mark.asyncio
async def test_upload_media_orchestrates_full_flow(monkeypatch):
    """upload_media should orchestrate init, chunks, and complete."""
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

    # Create a small test file
    file_content = b"test file content"
    file = UploadFile(
        filename="test.jpg",
        file=BytesIO(file_content),
        headers={"content-type": "image/jpeg"},
    )

    with (
        patch("fanvue_fastapi.media.initiate_upload") as mock_init,
        patch("fanvue_fastapi.media.get_upload_url") as mock_url,
        patch("fanvue_fastapi.media.upload_chunk") as mock_chunk,
        patch("fanvue_fastapi.media.complete_upload") as mock_complete,
    ):
        mock_init.return_value = {"mediaUuid": "media-123", "uploadId": "upload-456"}
        mock_url.return_value = "https://storage.example.com/signed"
        mock_chunk.return_value = '"etag1"'

        from fanvue_fastapi.media import upload_media

        result = await upload_media(file, "valid_token")

        assert result.success is True
        assert result.media_uuid == "media-123"
        assert result.error is None
        mock_init.assert_called_once()
        mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_upload_media_returns_error_on_failure(monkeypatch):
    """upload_media should return error details on failure."""
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

    file_content = b"test file content"
    file = UploadFile(
        filename="test.jpg",
        file=BytesIO(file_content),
        headers={"content-type": "image/jpeg"},
    )

    with patch("fanvue_fastapi.media.initiate_upload") as mock_init:
        from fanvue_fastapi.media import MediaUploadError

        mock_init.side_effect = MediaUploadError("API error")

        from fanvue_fastapi.media import upload_media

        result = await upload_media(file, "valid_token")

        assert result.success is False
        assert result.media_uuid is None
        assert result.error == "API error"

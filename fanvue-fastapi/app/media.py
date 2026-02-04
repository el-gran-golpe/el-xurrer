from typing import Dict

import httpx

from app.config import get_settings

CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


class MediaUploadError(Exception):
    """Error during media upload."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def initiate_upload(
    filename: str,
    content_type: str,
    access_token: str,
) -> Dict[str, str]:
    """Initiate a media upload session.

    Args:
        filename: Name of the file being uploaded
        content_type: MIME type of the file
        access_token: Valid Fanvue access token

    Returns:
        Dict with mediaUuid and uploadId

    Raises:
        MediaUploadError: If the upload initiation fails
    """
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.api_base_url}/media/uploads",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "filename": filename,
                "contentType": content_type,
            },
        )

    if response.status_code != 201:
        raise MediaUploadError(f"Failed to initiate upload: {response.status_code}")

    return response.json()

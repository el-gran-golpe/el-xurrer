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


async def get_upload_url(
    upload_id: str,
    part_number: int,
    access_token: str,
) -> str:
    """Get signed URL for uploading a chunk.

    Args:
        upload_id: The upload session ID
        part_number: Chunk number (1-indexed)
        access_token: Valid Fanvue access token

    Returns:
        Signed URL for PUT request

    Raises:
        MediaUploadError: If getting URL fails
    """
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.api_base_url}/media/uploads/{upload_id}/parts/{part_number}/url",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        raise MediaUploadError(f"Failed to get upload URL: {response.status_code}")

    return response.json()["url"]


async def upload_chunk(url: str, data: bytes) -> str:
    """Upload a chunk to the signed URL.

    Args:
        url: Signed URL for upload
        data: Chunk data to upload

    Returns:
        ETag from response headers

    Raises:
        MediaUploadError: If chunk upload fails
    """
    async with httpx.AsyncClient() as client:
        response = await client.put(url, content=data)

    if response.status_code not in (200, 201):
        raise MediaUploadError(f"Failed to upload chunk: {response.status_code}")

    return response.headers.get("ETag", "")

from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
from fastapi import UploadFile

from app.config import get_settings

CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


def get_media_type(content_type: str) -> str:
    """Determine Fanvue mediaType from MIME content type.

    Args:
        content_type: MIME type (e.g., 'image/jpeg', 'video/mp4')

    Returns:
        One of: 'image', 'video', 'audio', 'document'
    """
    if content_type.startswith("image/"):
        return "image"
    elif content_type.startswith("video/"):
        return "video"
    elif content_type.startswith("audio/"):
        return "audio"
    else:
        return "document"


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
                "name": filename,
                "mediaType": get_media_type(content_type),
                "contentType": content_type,
            },
        )

    if response.status_code != 200:
        error_detail = response.text
        raise MediaUploadError(
            f"Failed to initiate upload: {response.status_code} - {error_detail}"
        )

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
        error_detail = response.text
        raise MediaUploadError(
            f"Failed to get upload URL: {response.status_code} - {error_detail}"
        )

    return response.text


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
        error_detail = response.text
        raise MediaUploadError(
            f"Failed to upload chunk: {response.status_code} - {error_detail}"
        )

    return response.headers.get("ETag", "")


async def complete_upload(
    upload_id: str,
    etags: List[str],
    access_token: str,
) -> None:
    """Complete a multipart upload.

    Args:
        upload_id: The upload session ID
        etags: List of ETags from chunk uploads
        access_token: Valid Fanvue access token

    Raises:
        MediaUploadError: If completing upload fails
    """
    settings = get_settings()

    parts = [{"PartNumber": i + 1, "ETag": etag} for i, etag in enumerate(etags)]

    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{settings.api_base_url}/media/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"parts": parts},
        )

    if response.status_code not in (200, 204):
        error_detail = response.text
        raise MediaUploadError(
            f"Failed to complete upload: {response.status_code} - {error_detail}"
        )


@dataclass
class MediaUploadResult:
    """Result of a media upload attempt."""

    success: bool
    media_uuid: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None


async def upload_media(file: UploadFile, access_token: str) -> MediaUploadResult:
    """Upload a file to Fanvue using multipart upload.

    Args:
        file: The file to upload
        access_token: Valid Fanvue access token

    Returns:
        MediaUploadResult with success status and media_uuid or error
    """
    filename = file.filename or "unknown"
    content_type = file.content_type or "application/octet-stream"

    try:
        # Phase 1: Initiate upload
        init_result = await initiate_upload(filename, content_type, access_token)
        media_uuid = init_result["mediaUuid"]
        upload_id = init_result["uploadId"]

        # Phase 2: Upload chunks
        etags: List[str] = []
        part_number = 1

        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break

            url = await get_upload_url(upload_id, part_number, access_token)
            etag = await upload_chunk(url, chunk)
            etags.append(etag)
            part_number += 1

        # Phase 3: Complete upload
        await complete_upload(upload_id, etags, access_token)

        return MediaUploadResult(
            success=True,
            media_uuid=media_uuid,
            filename=filename,
        )

    except MediaUploadError as e:
        return MediaUploadResult(
            success=False,
            filename=filename,
            error=e.message,
        )
    except Exception as e:
        return MediaUploadResult(
            success=False,
            filename=filename,
            error=str(e),
        )

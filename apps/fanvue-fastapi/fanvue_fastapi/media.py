from typing import Dict, List

from fastapi import UploadFile
from fanvue_api_client import media as fanvue_media
from fanvue_api_client.media import MediaUploadError, MediaUploadResult

from fanvue_fastapi.config import get_settings

CHUNK_SIZE = fanvue_media.CHUNK_SIZE


def get_media_type(content_type: str) -> str:
    """Determine Fanvue mediaType from MIME content type.

    Args:
        content_type: MIME type (e.g., 'image/jpeg', 'video/mp4')

    Returns:
        One of: 'image', 'video', 'audio', 'document'
    """
    return fanvue_media.get_media_type(content_type)


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

    return await fanvue_media.initiate_upload(
        settings.api_base_url,
        filename,
        content_type,
        access_token,
    )


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

    return await fanvue_media.get_upload_url(
        settings.api_base_url,
        upload_id,
        part_number,
        access_token,
    )


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
    return await fanvue_media.upload_chunk(url, data)


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

    await fanvue_media.complete_upload(
        settings.api_base_url,
        upload_id,
        etags,
        access_token,
    )


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

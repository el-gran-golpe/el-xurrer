from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

import httpx


CHUNK_SIZE = 10 * 1024 * 1024


class UploadFileLike(Protocol):
    @property
    def filename(self) -> str | None: ...

    @property
    def content_type(self) -> str | None: ...

    async def read(self, size: int = -1) -> bytes: ...


def get_media_type(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "document"


class MediaUploadError(Exception):
    """Error during media upload."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def initiate_upload(
    api_base_url: str,
    filename: str,
    content_type: str,
    access_token: str,
) -> Dict[str, str]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base_url}/media/uploads",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "filename": filename,
                "name": filename,
                "mediaType": get_media_type(content_type),
                "contentType": content_type,
            },
        )

    if response.status_code != 200:
        raise MediaUploadError(
            f"Failed to initiate upload: {response.status_code} - {response.text}"
        )

    return response.json()


async def get_upload_url(
    api_base_url: str,
    upload_id: str,
    part_number: int,
    access_token: str,
) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{api_base_url}/media/uploads/{upload_id}/parts/{part_number}/url",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        raise MediaUploadError(
            f"Failed to get upload URL: {response.status_code} - {response.text}"
        )

    return response.text


async def upload_chunk(url: str, data: bytes) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.put(url, content=data)

    if response.status_code not in (200, 201):
        raise MediaUploadError(
            f"Failed to upload chunk: {response.status_code} - {response.text}"
        )

    return response.headers.get("ETag", "")


async def complete_upload(
    api_base_url: str,
    upload_id: str,
    etags: List[str],
    access_token: str,
) -> None:
    parts = [{"PartNumber": i + 1, "ETag": etag} for i, etag in enumerate(etags)]

    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{api_base_url}/media/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"parts": parts},
        )

    if response.status_code not in (200, 204):
        raise MediaUploadError(
            f"Failed to complete upload: {response.status_code} - {response.text}"
        )


@dataclass
class MediaUploadResult:
    success: bool
    media_uuid: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None


async def upload_media(
    file: UploadFileLike,
    access_token: str,
    api_base_url: str,
) -> MediaUploadResult:
    filename = file.filename or "unknown"
    content_type = file.content_type or "application/octet-stream"

    try:
        init_result = await initiate_upload(
            api_base_url,
            filename,
            content_type,
            access_token,
        )
        media_uuid = init_result["mediaUuid"]
        upload_id = init_result["uploadId"]

        etags: List[str] = []
        part_number = 1

        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break

            url = await get_upload_url(
                api_base_url,
                upload_id,
                part_number,
                access_token,
            )
            etag = await upload_chunk(url, chunk)
            etags.append(etag)
            part_number += 1

        await complete_upload(api_base_url, upload_id, etags, access_token)

        return MediaUploadResult(
            success=True,
            media_uuid=media_uuid,
            filename=filename,
        )
    except MediaUploadError as e:
        return MediaUploadResult(success=False, filename=filename, error=e.message)
    except Exception as e:
        return MediaUploadResult(success=False, filename=filename, error=str(e))

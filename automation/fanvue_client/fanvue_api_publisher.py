from pathlib import Path
from typing import Any

from loguru import logger

from main_components.common.types import Profile
from main_components.fanvue_auth import FanvueTokenManager


class FanvueAPIPublisher:
    """OAuth-based Fanvue publisher using API (replaces Selenium)."""

    def __init__(self, profile: Profile):
        self.profile = profile
        self.token_manager = FanvueTokenManager(profile.name)

    async def post_publication(
        self, file_path: Path, caption: str, publish_at: str | None = None
    ) -> dict[str, Any]:
        """Upload media and create post using Fanvue API.

        Args:
            file_path: Path to media file
            caption: Post caption text
            publish_at: ISO 8601 datetime string for scheduled publishing (None for immediate)

        Returns:
            Post data from Fanvue API

        Raises:
            AuthError: If authentication fails
            Exception: If upload or post creation fails
        """
        # 1. Ensure fresh access token
        access_token = await self.token_manager.ensure_valid_token()

        # 2. Upload media (reuse fanvue-fastapi/media.py logic)
        logger.info(f"Uploading media: {file_path.name}")
        media_uuid = await upload_media(file_path, access_token)
        logger.debug(f"Media uploaded: {media_uuid}")

        # 3. Create post (reuse fanvue-fastapi/posts.py logic)
        if publish_at:
            logger.info(
                f"Scheduling post for profile '{self.profile.name}' at {publish_at}"
            )
        else:
            logger.info(f"Creating immediate post for profile '{self.profile.name}'")

        post_data = await create_post(
            text=caption,
            media_uuids=[media_uuid],
            audience="subscribers",
            publish_at=publish_at,
            access_token=access_token,
        )

        logger.success(f"✓ Post created: {post_data['id']}")
        return post_data

    async def post_publication_batch(
        self, file_paths: list[Path], caption: str, publish_at: str | None = None
    ) -> dict[str, Any]:
        """Upload multiple media files and create single carousel post.

        Args:
            file_paths: List of paths to media files
            caption: Post caption text
            publish_at: ISO 8601 datetime string for scheduled publishing (None for immediate)

        Returns:
            Post data from Fanvue API

        Raises:
            AuthError: If authentication fails
            Exception: If upload or post creation fails
        """
        # 1. Ensure fresh access token
        access_token = await self.token_manager.ensure_valid_token()

        # 2. Upload all media files, collect UUIDs
        media_uuids = []
        for file_path in file_paths:
            logger.info(f"Uploading media: {file_path.name}")
            media_uuid = await upload_media(file_path, access_token)
            logger.debug(f"Media uploaded: {media_uuid}")
            media_uuids.append(media_uuid)

        # 3. Create single post with all media
        if publish_at:
            logger.info(
                f"Scheduling post with {len(media_uuids)} media file(s) for {publish_at}"
            )
        else:
            logger.info(
                f"Creating immediate post with {len(media_uuids)} media file(s)"
            )

        post_data = await create_post(
            text=caption,
            media_uuids=media_uuids,
            audience="subscribers",
            publish_at=publish_at,
            access_token=access_token,
        )

        logger.success(f"✓ Post created: {post_data['uuid']}")
        return post_data


class _UploadFileWrapper:
    """Minimal UploadFile-like wrapper for Path objects."""

    def __init__(self, file_path: Path, content_type: str):
        self.filename = file_path.name
        self.content_type = content_type
        self._file = open(file_path, "rb")

    async def read(self, size: int = -1) -> bytes:
        """Read bytes from file (async-compatible)."""
        return self._file.read(size)

    def close(self) -> None:
        """Close the underlying file."""
        self._file.close()


# Add imports for FastAPI fanvue-fastapi functions
async def upload_media(file_path: Path, access_token: str) -> str:
    """Upload media file to Fanvue.

    Args:
        file_path: Path to media file
        access_token: Valid Fanvue access token

    Returns:
        Media UUID

    Raises:
        Exception: If upload fails
    """
    import mimetypes
    import sys
    from pathlib import Path as PathLib

    # Add fanvue-fastapi to path
    fastapi_path = PathLib(__file__).parent.parent.parent / "fanvue-fastapi"
    if str(fastapi_path) not in sys.path:
        sys.path.insert(0, str(fastapi_path))

    from fanvue_fastapi.media import upload_media as api_upload_media

    # Determine content type
    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "application/octet-stream"

    # Create UploadFile-like wrapper
    upload_file = _UploadFileWrapper(file_path, content_type)

    try:
        # Upload and get result
        result = await api_upload_media(upload_file, access_token)

        if not result.success:
            raise Exception(f"Media upload failed: {result.error}")

        return result.media_uuid
    finally:
        upload_file.close()


async def create_post(
    text: str,
    media_uuids: list[str],
    audience: str,
    publish_at: str | None,
    access_token: str,
) -> dict[str, Any]:
    """Create post on Fanvue.

    Args:
        text: Post caption
        media_uuids: List of uploaded media UUIDs
        audience: Target audience
        publish_at: Scheduled publish time (ISO 8601)
        access_token: Valid Fanvue access token

    Returns:
        Post data
    """
    import sys
    from pathlib import Path as PathLib

    # Add fanvue-fastapi to path
    fastapi_path = PathLib(__file__).parent.parent.parent / "fanvue-fastapi"
    if str(fastapi_path) not in sys.path:
        sys.path.insert(0, str(fastapi_path))

    from fanvue_fastapi.posts import create_post as api_create_post

    return await api_create_post(text, media_uuids, audience, publish_at, access_token)

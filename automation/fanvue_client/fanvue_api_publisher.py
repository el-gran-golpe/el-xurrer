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

    async def post_publication(self, file_path: Path, caption: str) -> dict[str, Any]:
        """Upload media and create post using Fanvue API.

        Args:
            file_path: Path to media file
            caption: Post caption text

        Returns:
            Post data from Fanvue API

        Raises:
            AuthError: If authentication fails
            Exception: If upload or post creation fails
        """
        # 1. Ensure fresh access token
        access_token = await self.token_manager.ensure_valid_token()

        # 2. Upload media (reuse app/media.py logic)
        logger.info(f"Uploading media: {file_path.name}")
        media_uuid = await upload_media(file_path, access_token)
        logger.debug(f"Media uploaded: {media_uuid}")

        # 3. Create post (reuse app/posts.py logic)
        logger.info(f"Creating post for profile '{self.profile.name}'")
        post_data = await create_post(
            text=caption,
            media_uuids=[media_uuid],
            audience="subscribers",
            publish_at=None,  # Immediate post
            access_token=access_token,
        )

        logger.success(f"✓ Post created: {post_data['id']}")
        return post_data


# Add imports for FastAPI app functions
async def upload_media(file_path: Path, access_token: str) -> str:
    """Upload media file to Fanvue.

    Args:
        file_path: Path to media file
        access_token: Valid Fanvue access token

    Returns:
        Media UUID
    """
    import sys
    from pathlib import Path as PathLib

    # Add fanvue-fastapi to path
    fastapi_path = PathLib(__file__).parent.parent.parent / "fanvue-fastapi"
    if str(fastapi_path) not in sys.path:
        sys.path.insert(0, str(fastapi_path))

    from app.media import upload_media as api_upload_media

    return await api_upload_media(file_path, access_token)


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

    from app.posts import create_post as api_create_post

    return await api_create_post(text, media_uuids, audience, publish_at, access_token)

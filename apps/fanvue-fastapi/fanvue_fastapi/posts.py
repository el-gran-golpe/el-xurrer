from typing import Any, Dict, List, Optional

from fanvue_api_client.posts import PostCreationError
from fanvue_api_client.posts import create_post as client_create_post

from fanvue_fastapi.config import get_settings


__all__ = ["PostCreationError", "create_post"]


async def create_post(
    text: Optional[str],
    media_uuids: List[str],
    audience: str,
    publish_at: Optional[str],
    access_token: str,
) -> Dict[str, Any]:
    """Create a post on Fanvue."""
    settings = get_settings()
    return await client_create_post(
        api_base_url=settings.api_base_url,
        text=text,
        media_uuids=media_uuids,
        audience=audience,
        publish_at=publish_at,
        access_token=access_token,
    )

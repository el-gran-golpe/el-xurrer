from typing import Any, Dict, List, Optional

import httpx


class PostCreationError(Exception):
    """Error creating a post."""

    def __init__(self, message: str, status_code: int = 0):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def create_post(
    api_base_url: str,
    text: Optional[str],
    media_uuids: List[str],
    audience: str,
    publish_at: Optional[str],
    access_token: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"audience": audience}

    if text:
        payload["text"] = text
    if media_uuids:
        payload["mediaUuids"] = media_uuids
    if publish_at:
        payload["publishAt"] = publish_at

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base_url}/posts",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )

    if response.status_code != 201:
        raise PostCreationError(
            f"Failed to create post: {response.text}",
            status_code=response.status_code,
        )

    return response.json()

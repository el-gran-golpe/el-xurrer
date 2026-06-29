import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import requests
from loguru import logger

from ai_content_pipeline.config import settings
from ai_content_pipeline.domain.types import Profile

GRAPH_API_BASE_URL = "https://graph.facebook.com/v25.0"


class MetaPublisherError(RuntimeError):
    """Base error for Meta publishing failures."""


class MetaValidationError(MetaPublisherError):
    """Raised when Meta credentials or linked resources are invalid."""


class PublicationError(MetaPublisherError):
    """Raised when an upload or publish operation fails."""


def _redact_sensitive_values(
    message: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    redacted = message
    for payload in (params, data):
        if not payload:
            continue
        token = payload.get("access_token")
        if isinstance(token, str) and token:
            redacted = redacted.replace(token, "<redacted>")
    return redacted


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=params, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(
                url,
                params=params,
                data=data,
                files=files,
                timeout=timeout,
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        response_text = getattr(exc.response, "text", "")
        detail = f"{exc} / {response_text}" if response_text else str(exc)
        detail = _redact_sensitive_values(detail, params=params, data=data)
        raise MetaPublisherError(detail) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise MetaPublisherError(
            f"Invalid JSON response from {url}: {response.text}"
        ) from exc


async def _async_request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                response = await client.get(url, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = await client.post(
                    url,
                    params=params,
                    data=data,
                    files=files,
                    timeout=timeout,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = f"{exc} / {exc.response.text}" if exc.response.text else str(exc)
        detail = _redact_sensitive_values(detail, params=params, data=data)
        raise MetaPublisherError(detail) from exc
    except httpx.RequestError as exc:
        detail = _redact_sensitive_values(str(exc), params=params, data=data)
        raise MetaPublisherError(detail) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise MetaPublisherError(
            f"Invalid JSON response from {url}: {response.text}"
        ) from exc


def validate_meta_profile_auth(profile: Profile) -> None:
    """Validate that a profile's Meta credentials belong together.

    Confirms that the configured Facebook Page is linked to the expected
    Instagram professional account. This prevents credentials from different
    profiles or incorrectly linked accounts from reaching the publishing flow.

    Raises:
        MetaValidationError: If the Page has no linked Instagram account or its
            account ID differs from the configured Instagram account ID.
        MetaPublisherError: If the Graph API request fails.
    """
    credentials = profile.meta_credentials

    # Check the Page-to-Instagram relationship, not only whether the token is valid.
    payload = {
        "fields": "instagram_business_account",
        "access_token": credentials.facebook_page_access_token,
    }
    data = _request_json(
        "GET",
        f"{GRAPH_API_BASE_URL}/{credentials.facebook_page_id}",
        params=payload,
    )

    linked_account = data.get("instagram_business_account")
    if not isinstance(linked_account, dict):
        raise MetaValidationError(
            "Facebook Page token did not return instagram_business_account for "
            f"Page {credentials.facebook_page_id}."
        )

    returned_user_id = str(linked_account.get("id", ""))
    if returned_user_id != credentials.instagram_account_id:
        raise MetaValidationError(
            "Facebook Page token does not match INSTAGRAM_ACCOUNT_ID. "
            f"Expected {credentials.instagram_account_id}, "
            f"got {returned_user_id or 'missing'}."
        )

    logger.info(
        "Validated Facebook Page {} for Instagram account {}",
        credentials.facebook_page_id,
        credentials.instagram_account_id,
    )


class InstagramPublisher:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.account_id = profile.meta_credentials.instagram_account_id
        self.page_access_token = profile.meta_credentials.facebook_page_access_token
        self.base_url = GRAPH_API_BASE_URL
        self._validate_credentials()

    def _validate_credentials(self) -> None:
        validate_meta_profile_auth(self.profile)

    async def upload_publication(
        self,
        img_paths: list[Path],
        caption: str,
        upload_time: datetime | None,
        media_stager: "FacebookMediaStager",
    ) -> dict[str, str]:
        if len(caption) > 2200:
            raise ValueError(
                "Caption exceeds the maximum allowed length of 2,200 characters."
            )

        media_ids: list[str] = []

        for img_path in img_paths:
            image_url = await media_stager.upload_photo_and_get_cdn_url(img_path)

            payload: dict[str, str] = {
                "image_url": image_url,
                "access_token": self.page_access_token,
            }

            if len(img_paths) == 1:
                payload["caption"] = caption
            else:
                payload["is_carousel_item"] = "true"

            data = await _async_request_json(
                "POST",
                f"{self.base_url}/{self.account_id}/media",
                data=payload,
            )
            media_id = str(data.get("id", ""))
            if not media_id:
                raise PublicationError(
                    f"Instagram media container creation returned no id for {img_path}."
                )

            media_ids.append(media_id)
            logger.info(
                "Created Instagram media container for {} with ID {}",
                img_path,
                media_id,
            )

        if not media_ids:
            raise PublicationError("No Instagram media containers were created.")

        if len(media_ids) == 1:
            creation_id = media_ids[0]
        else:
            data = await _async_request_json(
                "POST",
                f"{self.base_url}/{self.account_id}/media",
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(media_ids),
                    "caption": caption,
                    "access_token": self.page_access_token,
                },
            )
            creation_id = str(data.get("id", ""))
            if not creation_id:
                raise PublicationError(
                    "Instagram carousel container creation returned no id."
                )
            logger.info("Created Instagram carousel container {}", creation_id)

        if not await self._wait_for_media_ready(creation_id):
            raise PublicationError(
                f"Instagram media container {creation_id} was not ready for publishing."
            )

        result = await _async_request_json(
            "POST",
            f"{self.base_url}/{self.account_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": self.page_access_token,
            },
        )

        scheduled_for = upload_time.isoformat() if upload_time else "immediate publish"
        logger.success(
            "Instagram publication created for {}: {}",
            scheduled_for,
            result,
        )
        return {
            "id": str(result.get("id", "")),
            "permalink": str(result.get("permalink", "")),
            "status": "scheduled" if upload_time else "published",
        }

    async def _wait_for_media_ready(
        self,
        creation_id: str,
        max_attempts: int = 10,
        delay_seconds: int = 5,
    ) -> bool:
        params = {
            "fields": "status_code",
            "access_token": self.page_access_token,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                data = await _async_request_json(
                    "GET",
                    f"{self.base_url}/{creation_id}",
                    params=params,
                )
            except MetaPublisherError as exc:
                logger.error(
                    "Error while polling Instagram media container {} (attempt {}/{}): {}",
                    creation_id,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay_seconds)
                continue

            status = data.get("status_code")
            logger.info(
                "Instagram media container {} status {} (attempt {}/{})",
                creation_id,
                status,
                attempt,
                max_attempts,
            )

            if status == "FINISHED":
                return True
            if status == "ERROR":
                logger.error(
                    "Instagram media container {} entered ERROR state: {}",
                    creation_id,
                    data,
                )
                return False

            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)

        logger.error(
            "Instagram media container {} was not ready after {} attempts",
            creation_id,
            max_attempts,
        )
        return False


class FacebookMediaStager:
    """Upload media to Facebook only to obtain public CDN URLs for Instagram publishing.

    This helper exists solely because Instagram publishing requires public media URLs.
    The project intentionally uses Facebook CDN staging to preserve a zero-dollar
    runtime, and this class must not publish Facebook posts.
    """

    def __init__(self):
        self.base_url = GRAPH_API_BASE_URL
        self.page_id = ""
        self.page_access_token = ""
        self._load_credentials()

    def _load_credentials(self) -> None:
        staging = settings.get_facebook_media_staging_credentials()
        self.page_id = staging.page_id
        self.page_access_token = staging.page_access_token
        logger.info(
            "Using shared Facebook media staging page {} for Instagram CDN URLs",
            self.page_id,
        )

    async def _upload_photo(self, img_path: Path) -> str:
        with img_path.open("rb") as source_file:
            data = await _async_request_json(
                "POST",
                f"{self.base_url}/{self.page_id}/photos",
                files={"source": source_file},
                data={
                    "published": "false",
                    "access_token": self.page_access_token,
                },
            )

        photo_id = str(data.get("id", ""))
        if not photo_id:
            raise PublicationError(
                f"Facebook staging upload returned no photo id for {img_path}."
            )

        logger.info("Uploaded Facebook staging photo {} as {}", img_path, photo_id)
        return photo_id

    async def upload_photo_and_get_cdn_url(self, img_path: Path) -> str:
        photo_id = await self._upload_photo(img_path)

        details = await _async_request_json(
            "GET",
            f"{self.base_url}/{photo_id}",
            params={
                "fields": "images",
                "access_token": self.page_access_token,
            },
        )

        images = details.get("images", [])
        if not images:
            raise PublicationError(
                f"Facebook staging photo {photo_id} returned no images payload."
            )

        images.sort(key=lambda image: image.get("width", 0), reverse=True)
        cdn_url = images[0].get("source")
        if not cdn_url:
            raise PublicationError(
                f"Facebook staging photo {photo_id} returned no CDN source URL."
            )

        logger.info("Using Facebook CDN URL {} for Instagram upload", cdn_url)
        return str(cdn_url)


class MetaPublisher:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.instagram = InstagramPublisher(profile)
        self.media_stager = FacebookMediaStager()

    async def upload_publication(
        self,
        img_paths: list[Path],
        caption: str,
        upload_time: datetime | None,
    ) -> dict[str, Any]:
        if self.instagram is None or self.media_stager is None:
            raise RuntimeError(
                "MetaPublisher is not initialised. Use 'await MetaPublisher.create(profile)' instead of the constructor."
            )
        instagram_result = await self.instagram.upload_publication(
            img_paths,
            caption,
            upload_time,
            self.media_stager,
        )
        if not instagram_result:
            raise PublicationError("Instagram publication failed")

        return {"instagram": instagram_result}

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from main_components.config import settings
from main_components.common.types import Profile


class MetaPublisherError(RuntimeError):
    """Base error for Meta publishing failures."""


class MetaValidationError(MetaPublisherError):
    """Raised when Meta credentials or linked resources are invalid."""


class PublicationError(MetaPublisherError):
    """Raised when an upload or publish operation fails."""


def _require_setting(value: str | None, setting_name: str) -> str:
    if not value:
        raise MetaValidationError(
            f"Missing required Meta setting: {setting_name}. Check your .env configuration."
        )
    return value


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
        raise MetaPublisherError(detail) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise MetaPublisherError(f"Invalid JSON response from {url}: {response.text}") from exc


class InstagramPublisher:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.account_id = _require_setting(
            profile.meta_credentials.instagram_account_id,
            f"{profile.name.upper()}_INSTAGRAM_ACCOUNT_ID",
        )
        self.user_access_token = _require_setting(
            profile.meta_credentials.instagram_user_access_token,
            f"{profile.name.upper()}_INSTAGRAM_USER_ACCESS_TOKEN",
        )
        self.base_url = "https://graph.instagram.com/v21.0"
        self.username = ""
        self.app_user_id = ""
        self._validate_credentials()

    def _validate_credentials(self) -> None:
        payload = {
            "fields": "id,user_id,username",
            "access_token": self.user_access_token,
        }
        data = _request_json("GET", f"{self.base_url}/me", params=payload)

        returned_user_id = str(data.get("user_id", ""))
        if returned_user_id != self.account_id:
            raise MetaValidationError(
                "Instagram token does not match INSTAGRAM_ACCOUNT_ID. "
                f"Expected {self.account_id}, got {returned_user_id or 'missing'}."
            )

        self.app_user_id = str(data.get("id", ""))
        self.username = str(data.get("username", ""))
        logger.info(
            "Validated Instagram publishing credentials for account {} ({})",
            self.account_id,
            self.username or "unknown",
        )

    def upload_publication(
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
            image_url = media_stager.upload_photo_and_get_cdn_url(img_path)

            payload: dict[str, str] = {
                "image_url": image_url,
                "access_token": self.user_access_token,
            }

            if len(img_paths) == 1:
                payload["caption"] = caption
            else:
                payload["is_carousel_item"] = "true"

            data = _request_json(
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
            data = _request_json(
                "POST",
                f"{self.base_url}/{self.account_id}/media",
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(media_ids),
                    "caption": caption,
                    "access_token": self.user_access_token,
                },
            )
            creation_id = str(data.get("id", ""))
            if not creation_id:
                raise PublicationError("Instagram carousel container creation returned no id.")
            logger.info("Created Instagram carousel container {}", creation_id)

        if not self._wait_for_media_ready(creation_id):
            raise PublicationError(
                f"Instagram media container {creation_id} was not ready for publishing."
            )

        result = _request_json(
            "POST",
            f"{self.base_url}/{self.account_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": self.user_access_token,
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

    def _wait_for_media_ready(
        self,
        creation_id: str,
        max_attempts: int = 10,
        delay_seconds: int = 5,
    ) -> bool:
        params = {
            "fields": "status_code",
            "access_token": self.user_access_token,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                data = _request_json(
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
                    time.sleep(delay_seconds)
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
                time.sleep(delay_seconds)

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
        self.base_url = "https://graph.facebook.com/v21.0"
        self.page_id = ""
        self.page_access_token = ""
        self.user_access_token = ""
        self._load_credentials()

    def _load_credentials(self) -> None:
        staging = settings.get_facebook_media_staging_credentials()
        self.page_id = _require_setting(
            staging.page_id,
            "FACEBOOK_STAGING_PAGE_ID",
        )
        self.user_access_token = _require_setting(
            staging.user_access_token,
            "FACEBOOK_STAGING_USER_ACCESS_TOKEN",
        )
        self.page_access_token = self._lookup_page_access_token(
            page_id=self.page_id,
            user_access_token=self.user_access_token,
        )
        logger.info(
            "Using shared Facebook media staging page {} for Instagram CDN URLs",
            self.page_id,
        )

    def _lookup_page_access_token(
        self,
        *,
        page_id: str,
        user_access_token: str,
    ) -> str:
        payload = {
            "fields": "id,name,access_token,tasks",
            "access_token": user_access_token,
        }
        try:
            data = _request_json("GET", f"{self.base_url}/me/accounts", params=payload)
        except MetaPublisherError as exc:
            raise MetaValidationError(
                f"Unable to resolve a page access token for Facebook staging page {page_id}: {exc}"
            ) from exc

        pages = data.get("data", [])
        if not isinstance(pages, list):
            raise MetaValidationError(
                f"Unexpected Facebook /me/accounts response shape: {data}"
            )

        visible_pages: list[str] = []
        for page in pages:
            current_page_id = str(page.get("id", ""))
            current_page_name = str(page.get("name", "unknown"))
            if current_page_id:
                visible_pages.append(f"{current_page_name} ({current_page_id})")

            if current_page_id != page_id:
                continue

            page_access_token = str(page.get("access_token", ""))
            if not page_access_token:
                raise MetaValidationError(
                    f"Facebook staging page {page_id} returned no page access token in /me/accounts."
                )
            return page_access_token

        visible_pages_text = ", ".join(visible_pages) if visible_pages else "none"
        raise MetaValidationError(
            "FACEBOOK_STAGING_PAGE_ID is not managed by FACEBOOK_STAGING_USER_ACCESS_TOKEN. "
            f"Configured page id: {page_id}. Visible pages: {visible_pages_text}."
        )

    def _upload_photo(self, img_path: Path) -> str:
        with img_path.open("rb") as source_file:
            data = _request_json(
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

    def upload_photo_and_get_cdn_url(self, img_path: Path) -> str:
        photo_id = self._upload_photo(img_path)

        details = _request_json(
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

    def upload_publication(
        self,
        img_paths: list[Path],
        caption: str,
        upload_time: datetime | None,
    ) -> dict[str, Any]:
        instagram_result = self.instagram.upload_publication(
            img_paths,
            caption,
            upload_time,
            self.media_stager,
        )
        if not instagram_result:
            raise PublicationError("Instagram publication failed")

        return {"instagram": instagram_result}

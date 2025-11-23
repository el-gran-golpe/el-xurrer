import sys
import os
from pathlib import Path
from datetime import datetime
import json

import requests
from loguru import logger

from main_components.config import settings


class GraphAPI:
    def __init__(self):
        self.account_id = settings.instagram_account_id
        self.user_access_token = settings.user_access_token
        self.app_scoped_user_id = settings.app_scoped_user_id
        self.base_url = "https://graph.facebook.com/v21.0"
        self.page_access_token = self._get_page_access_token()
        self.page_id = self._get_page_id()

    def upload_instagram_publication(
        self, img_paths: list[Path], caption: str, upload_time: datetime
    ):
        if len(caption) > 2200:
            raise ValueError(
                "Caption exceeds the maximum allowed length of 2,200 characters."
            )

        media_ids = []

        for img_path in img_paths:
            # --- Meta CDN step instead of ImgHippo ---
            try:
                # 1) Upload the local image as an unpublished photo to the FB Page
                # 2) Get the CDN URL and use it as image_url for Instagram
                image_url = self._upload_photo_to_facebook_and_get_cdn_url(img_path)

                url = f"{self.base_url}/{self.account_id}/media"
                payload = {
                    "image_url": image_url,
                    "access_token": self.page_access_token,
                }

                # Single image: put caption here
                if len(img_paths) == 1:
                    payload["caption"] = caption
                # Carousel items inherit caption from parent container
                if len(img_paths) > 1:
                    payload["is_carousel_item"] = "true"

                response = requests.post(url, data=payload, timeout=30)
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as http_err:
                    logger.error(
                        "Error creating IG media container for {}: {} / {}",
                        img_path,
                        http_err,
                        response.text,
                    )
                    return None

                media_id = str(response.json().get("id"))
                media_ids.append(media_id)
                logger.info(
                    "Created IG media container for {} with ID: {}", img_path, media_id
                )

            except requests.exceptions.RequestException as e:
                logger.error(
                    "An error occurred while creating IG media container for {}: {}",
                    img_path,
                    e,
                )
                return None
            except Exception as e:
                logger.error(
                    "Non-HTTP error while preparing IG media for {}: {}", img_path, e
                )
                return None

        # --- Carousel or single media publish ---
        if len(media_ids) == 1:
            creation_id = media_ids[0]
        else:
            try:
                carousel_url = "{}/{}/media".format(self.base_url, self.account_id)
                carousel_payload = {
                    "media_type": "CAROUSEL",
                    "children": ",".join(media_ids),
                    "caption": caption,
                    "access_token": self.page_access_token,
                }
                carousel_response = requests.post(
                    carousel_url, data=carousel_payload, timeout=30
                )
                try:
                    carousel_response.raise_for_status()
                except requests.exceptions.HTTPError as http_err:
                    logger.error(
                        "Error creating IG carousel container: {} / {}",
                        http_err,
                        carousel_response.text,
                    )
                    return None

                creation_id = carousel_response.json().get("id")
                logger.info("Created carousel container with ID: {}", creation_id)
            except requests.exceptions.RequestException as e:
                logger.error(
                    "An error occurred while creating the carousel container: {}", e
                )
                return None

        # --- Publish the media (or carousel) ---
        try:
            publish_url = "{}/{}/media_publish".format(self.base_url, self.account_id)
            publish_payload = {
                "creation_id": creation_id,
                "access_token": self.page_access_token,
            }

            publish_response = requests.post(
                publish_url, data=publish_payload, timeout=30
            )
            try:
                publish_response.raise_for_status()
            except requests.exceptions.HTTPError as http_err:
                logger.error(
                    "Error publishing IG media: {} / {}",
                    http_err,
                    publish_response.text,
                )
                return None

            result = publish_response.json()

            status = "scheduled" if upload_time else "published"
            logger.success("Instagram post {} published: {}", status, result)

            return {
                "id": result.get("id"),
                "permalink": result.get("permalink", ""),
                "status": status,
            }

        except requests.exceptions.RequestException as e:
            logger.error("An error occurred while publishing the Instagram post: {}", e)
            return None

    def upload_facebook_publication(
        self, img_paths: list, caption: str, upload_time=datetime
    ):
        if isinstance(img_paths, str):
            img_paths = [img_paths]

        media_ids = []

        for img_path in img_paths:
            url = "{}/{}/photos".format(self.base_url, self.page_id)
            files = {"source": open(img_path, "rb")}
            data = {
                "published": "false",
                "access_token": self.page_access_token,
            }

            try:
                response = requests.post(url, files=files, data=data, timeout=30)
                response.raise_for_status()
                media_id = response.json().get("id")
                media_ids.append({"media_fbid": media_id})
                logger.info("Uploaded photo {} with media ID: {}", img_path, media_id)
            except requests.exceptions.RequestException as e:
                logger.error("An error occurred while uploading {}: {}", img_path, e)
                return None

        post_url = "{}/{}/feed".format(self.base_url, self.page_id)
        post_data = {
            "attached_media": json.dumps(media_ids),
            "message": caption,
            "access_token": self.page_access_token,
        }

        try:
            post_response = requests.post(post_url, data=post_data, timeout=30)
            post_response.raise_for_status()
            logger.info("Post created successfully:", post_response.json())
            return post_response.json()
        except requests.exceptions.RequestException as e:
            logger.error("An error occurred while creating the post: {}", e)
            return None

    def _get_page_id(self):
        """Retrieve the Page ID using the User Access Token."""
        url = "{}/{}/accounts".format(self.base_url, self.app_scoped_user_id)
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            for page in pages:
                if "id" in page:
                    print("Retrieved Page ID for page: {}".format(page["name"]))
                    return page["id"]

            raise ValueError("No page found with the linked Facebook Business Account.")
        except requests.exceptions.RequestException as e:
            logger.info("An error occurred while retrieving the Page ID: {}", e)
            return None  # Return None instead of sys.exit(1)

    def _get_page_access_token(self):
        """Retrieve the Page Access Token using the User Access Token."""
        url = "{}/{}/accounts".format(self.base_url, self.app_scoped_user_id)
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            for page in pages:
                if "access_token" in page:
                    logger.info(
                        "Retrieved Page Access Token for page: {}", page["name"]
                    )
                    return page["access_token"]

            raise ValueError(
                "No page found with the linked Instagram Business Account."
            )
        except requests.exceptions.RequestException as e:
            logger.info(
                "An error occurred while retrieving the Page Access Token: {}", e
            )
            return None  # Return None instead of sys.exit(1)

        # NEW: helper to upload to FB Page and get Meta CDN URL

    def _upload_photo_to_facebook_and_get_cdn_url(self, img_path: Path) -> str:
        """
        Uploads img_path to the Facebook Page as an unpublished photo,
        then returns the CDN URL (largest image variant) to be used as
        image_url for Instagram.
        """
        photos_url = f"{self.base_url}/{self.page_id}/photos"

        # 1) Upload as unpublished photo
        with img_path.open("rb") as f:
            files = {"source": f}
            data = {
                "published": "false",
                "access_token": self.page_access_token,
            }
            resp = requests.post(photos_url, files=files, data=data, timeout=30)
        resp.raise_for_status()
        photo_json = resp.json()
        photo_id = photo_json.get("id")
        if not photo_id:
            raise RuntimeError(f"No 'id' in FB photo upload response: {photo_json}")
        logger.info("Uploaded helper photo {} to FB with id {}", img_path, photo_id)

        # 2) Get image variants to obtain the CDN URL
        details_url = f"{self.base_url}/{photo_id}"
        params = {
            "fields": "images",
            "access_token": self.page_access_token,
        }
        details_resp = requests.get(details_url, params=params, timeout=30)
        details_resp.raise_for_status()
        data = details_resp.json()
        images = data.get("images", [])
        if not images:
            raise RuntimeError(
                f"No 'images' field returned for FB photo {photo_id}: {data}"
            )

        # Choose the largest variant (by width)
        images.sort(key=lambda i: i.get("width", 0), reverse=True)
        cdn_url = images[0].get("source")
        if not cdn_url:
            raise RuntimeError(
                f"No 'source' field in images list for FB photo {photo_id}: {images[0]}"
            )

        logger.info("Using FB CDN URL for Instagram upload: {}", cdn_url)
        return cdn_url

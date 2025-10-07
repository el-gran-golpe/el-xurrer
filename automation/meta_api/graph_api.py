import sys
import os
from pathlib import Path

import dotenv
import requests
import json
from datetime import datetime
from loguru import logger
from generation_tools.free_image_url_generator.imghippo import ImgHippo

META_API_KEY = os.path.join(os.path.dirname(__file__), "api_key_instagram.env")


class GraphAPI:
    def __init__(self):
        dotenv.load_dotenv(META_API_KEY)
        self.account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
        self.user_access_token = os.getenv("USER_ACCESS_TOKEN")
        self.app_scoped_user_id = os.getenv("APP_SCOPED_USER_ID")
        assert self.account_id, "Instagram account ID not found in {}.".format(
            META_API_KEY
        )
        assert self.user_access_token, "Meta user access token not found in {}.".format(
            META_API_KEY
        )
        assert self.app_scoped_user_id, (
            "Meta app scoped user ID not found in {}.".format(META_API_KEY)
        )
        self.base_url = "https://graph.facebook.com/v21.0"
        self.page_access_token = self._get_page_access_token()
        self.page_id = self._get_page_id()

    def _get_page_id(self):
        """Retrieve the Page ID using the User Access Token."""
        url = "{}/{}/accounts".format(self.base_url, self.app_scoped_user_id)
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            # Iterate through pages and return the first page_id found
            for page in pages:
                if "id" in page:
                    print("Retrieved Page ID for page: {}".format(page["name"]))
                    return page["id"]

            raise ValueError("No page found with the linked Facebook Business Account.")
        except requests.exceptions.RequestException as e:
            logger.info("An error occurred while retrieving the Page ID: {}", e)
            sys.exit(1)

    def _get_page_access_token(self):
        """Retrieve the Page Access Token using the User Access Token."""
        url = "{}/{}/accounts".format(self.base_url, self.app_scoped_user_id)
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            # Iterate through pages and return the first access_token found
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
            sys.exit(1)

    def upload_instagram_publication(
        self, img_paths: list[Path], caption: str, upload_time: datetime
    ):
        # TODO: check this upload_time and the img_Paths

        if len(caption) > 2200:
            raise ValueError(
                "Caption exceeds the maximum allowed length of 2,200 characters."
            )

        media_ids = []

        # Step 1: Create media containers for each image
        for img_path in img_paths:
            assert img_path.suffix.lower() in {".png", ".jpg", ".jpeg"}, (
                "Each image file must be a .png, .jpg, or .jpeg, got {}",
                img_path.suffix,
            )

            try:
                # Get image URL from ImgHippo
                img_hippo = ImgHippo()
                image_url = img_hippo.get_url_for_image(img_path)

                url = "{}/{}/media".format(self.base_url, self.account_id)
                payload = {
                    "image_url": image_url,
                    "access_token": self.page_access_token,
                }

                # Add caption if a single image; carousel items will inherit caption later
                if len(img_paths) == 1:
                    payload["caption"] = caption

                # For multiple images, mark as a carousel item
                if len(img_paths) > 1:
                    payload["is_carousel_item"] = "true"

                response = requests.post(url, data=payload)
                response.raise_for_status()
                media_id = str(response.json().get("id"))
                media_ids.append(media_id)
                logger.info(
                    "Created media container for {} with ID: {}", img_path, media_id
                )

            except requests.exceptions.RequestException as e:
                logger.error(
                    "An error occurred while creating media container for {}: {}",
                    img_path,
                    e,
                )
                return None

        # Step 2: Create a carousel container if needed
        if len(media_ids) == 1:
            creation_id = media_ids[0]
        else:
            try:
                carousel_url = "{}/{}/media".format(self.base_url, self.account_id)
                carousel_payload = {
                    "media_type": "CAROUSEL",
                    "children": ",".join(
                        media_ids
                    ),  # Comma-separated list of media IDs
                    "caption": caption,
                    "access_token": self.page_access_token,
                }
                carousel_response = requests.post(carousel_url, data=carousel_payload)
                carousel_response.raise_for_status()
                creation_id = carousel_response.json().get("id")
                logger.info("Created carousel container with ID: {}", creation_id)
            except requests.exceptions.RequestException as e:
                logger.info(
                    "An error occurred while creating the carousel container: {}", e
                )
                return None

        # Step 3: Schedule the post by converting the ISO time to Unix timestamp
        try:
            publish_url = "{}/{}/media_publish".format(self.base_url, self.account_id)
            publish_payload = {
                "creation_id": creation_id,
                "access_token": self.page_access_token,
            }

            if upload_time:
                scheduled_timestamp = int(upload_time.timestamp())
                publish_payload["published"] = "false"  # Do not publish immediately
                publish_payload["scheduled_publish_time"] = scheduled_timestamp

            publish_response = requests.post(publish_url, data=publish_payload)
            publish_response.raise_for_status()
            result = publish_response.json()

            status = "scheduled" if upload_time else "published"
            logger.info("Instagram post {} successfully: {}", status, result)

            return {
                "id": result.get("id"),
                "permalink": result.get("permalink", ""),
                "status": status,
            }

        except requests.exceptions.RequestException as e:
            logger.info("An error occurred while publishing the Instagram post: {}", e)
            return None

    def upload_facebook_publication(
        self, img_paths: list, caption: str, upload_time=datetime
    ):
        # FIXME: upload_time_str is not used, so now facebook publications are post immediately
        """
        Uploads one or multiple images as a scheduled post on the Facebook Page.

        Parameters:
            - img_paths (list): List of image paths to upload.
            - caption (str): Caption for the post.
            - upload_time_str (str, optional): ISO formatted upload time (e.g., '2023-10-16T09:00:00Z').
                                               If not provided, post is published immediately.

        Returns:
            - dict: The response from the Facebook API if successful, None otherwise.
        """
        # Ensure img_paths is a list
        if isinstance(img_paths, str):
            img_paths = [img_paths]

        media_ids = []

        # Step 1: Upload each photo as unpublished media
        for img_path in img_paths:
            url = "{}/{}/photos".format(self.base_url, self.page_id)
            files = {"source": open(img_path, "rb")}
            data = {
                "published": "false",  # Upload as unpublished media
                "access_token": self.page_access_token,
            }

            try:
                response = requests.post(url, files=files, data=data)
                response.raise_for_status()
                media_id = response.json().get("id")
                media_ids.append({"media_fbid": media_id})
                logger.info("Uploaded photo {} with media ID: {}", img_path, media_id)
            except requests.exceptions.RequestException as e:
                logger.info("An error occurred while uploading {}: {}", img_path, e)
                return None

        # Step 2: Create a post with attached media
        post_url = "{}/{}/feed".format(self.base_url, self.page_id)
        post_data = {
            "attached_media": json.dumps(media_ids),
            "message": caption,
            "access_token": self.page_access_token,
        }

        try:
            post_response = requests.post(post_url, data=post_data)
            post_response.raise_for_status()
            logger.info("Post created successfully:", post_response.json())
            return post_response.json()
        except requests.exceptions.RequestException as e:
            logger.info("An error occurred while creating the post: {}", e)
            return None

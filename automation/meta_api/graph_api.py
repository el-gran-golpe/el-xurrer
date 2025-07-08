import sys
import os
from pathlib import Path
from typing import List

import dotenv
import requests
import json
from datetime import datetime

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from generation_tools.free_image_url_generator.imghippo import ImgHippo

META_API_KEY = os.path.join(os.path.dirname(__file__), "api_key_instagram.env")


class GraphAPI:
    def __init__(self):
        dotenv.load_dotenv(META_API_KEY)
        self.account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
        self.user_access_token = os.getenv("USER_ACCESS_TOKEN")
        self.app_scoped_user_id = os.getenv("APP_SCOPED_USER_ID")
        assert self.account_id, f"Instagram account ID not found in {META_API_KEY}."
        assert self.user_access_token, (
            f"Meta user access token not found in {META_API_KEY}."
        )
        assert self.app_scoped_user_id, (
            f"Meta app scoped user ID not found in {META_API_KEY}."
        )
        self.base_url = "https://graph.facebook.com/v21.0"
        self.page_access_token = self._get_page_access_token()
        self.page_id = self._get_page_id()

    def _get_page_id(self):
        """Retrieve the Page ID using the User Access Token."""
        url = f"{self.base_url}/{self.app_scoped_user_id}/accounts"
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            # Iterate through pages and return the first page_id found
            for page in pages:
                if "id" in page:
                    print(f"Retrieved Page ID for page: {page['name']}")
                    return page["id"]

            raise ValueError("No page found with the linked Facebook Business Account.")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while retrieving the Page ID: {e}")
            sys.exit(1)

    def _get_page_access_token(self):
        """Retrieve the Page Access Token using the User Access Token."""
        url = f"{self.base_url}/{self.app_scoped_user_id}/accounts"
        payload = {"access_token": self.user_access_token}

        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])

            # Iterate through pages and return the first access_token found
            for page in pages:
                if "access_token" in page:
                    print(f"Retrieved Page Access Token for page: {page['name']}")
                    return page["access_token"]

            raise ValueError(
                "No page found with the linked Instagram Business Account."
            )
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while retrieving the Page Access Token: {e}")
            sys.exit(1)

    def upload_instagram_publication(
        self, img_paths: List[Path], caption: str, upload_time: datetime
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
                f"Each image file must be a .png, .jpg, or .jpeg, got {img_path.suffix}"
            )

            try:
                # Get image URL from ImgHippo
                img_hippo = ImgHippo()
                image_url = img_hippo.get_url_for_image(img_path)

                url = f"{self.base_url}/{self.account_id}/media"
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
                print(f"Created media container for {img_path} with ID: {media_id}")

            except requests.exceptions.RequestException as e:
                print(
                    f"An error occurred while creating media container for {img_path}: {e}"
                )
                if response is not None:
                    print(f"Response content: {response.content.decode()}")
                return None

        # Step 2: Create a carousel container if needed
        if len(media_ids) == 1:
            creation_id = media_ids[0]
        else:
            try:
                carousel_url = f"{self.base_url}/{self.account_id}/media"
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
                print(f"Created carousel container with ID: {creation_id}")
            except requests.exceptions.RequestException as e:
                print(f"An error occurred while creating the carousel container: {e}")
                if "carousel_response" in locals() and carousel_response is not None:
                    print(f"Response content: {carousel_response.content.decode()}")
                return None

        # Step 3: Schedule the post by converting the ISO time to Unix timestamp
        try:
            publish_url = f"{self.base_url}/{self.account_id}/media_publish"
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
            print(f"Instagram post {status} successfully:", result)

            return {
                "id": result.get("id"),
                "permalink": result.get("permalink", ""),
                "status": status,
            }

        except requests.exceptions.RequestException as e:
            print(f"An error occurred while publishing the Instagram post: {e}")
            if "publish_response" in locals() and publish_response is not None:
                print(f"Response content: {publish_response.content.decode()}")
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
            url = f"{self.base_url}/{self.page_id}/photos"
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
                print(f"Uploaded photo {img_path} with media ID: {media_id}")
            except requests.exceptions.RequestException as e:
                print(f"An error occurred while uploading {img_path}: {e}")
                return None

        # Step 2: Create a post with attached media
        post_url = f"{self.base_url}/{self.page_id}/feed"
        post_data = {
            "attached_media": json.dumps(media_ids),
            "message": caption,
            "access_token": self.page_access_token,
        }

        try:
            post_response = requests.post(post_url, data=post_data)
            post_response.raise_for_status()
            print("Post created successfully:", post_response.json())
            return post_response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while creating the post: {e}")
            return None


# if __name__ == "__main__":
# graph_api = GraphAPI()

# Single image case
# img_paths = [r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_4\standing-strong_2.png"]
# caption = "How you all doing? Tell me in the comments! 🌟"
# response = graph_api.upload_instagram_publication(img_paths, caption)

# Multiple images case
# img_paths = [
#     r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_4\standing-strong_0.png",
#     r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_4\standing-strong_1.png",
# ]
# caption = "Let’s talk, my beautiful community! 💖 I want to hear your journeys toward authenticity—let's uplift each other! 😇"
# response = graph_api.upload_instagram_publication(img_paths, caption)

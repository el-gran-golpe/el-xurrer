import os
import requests
from dotenv import load_dotenv
from typing import List, Optional
import time

class InstagramUploader:
    def __init__(self):
        # Load the Instagram API token and user ID from the environment file
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'api_key_instagram.env')
        load_dotenv(env_path)
        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.user_id = os.getenv('INSTAGRAM_USER_ID')  # Add your Instagram user ID
        self.base_url = "https://graph.facebook.com/v17.0"

        # Ensure that necessary environment variables are loaded
        assert self.access_token, "INSTAGRAM_ACCESS_TOKEN not found in environment variables."
        assert self.user_id, "INSTAGRAM_USER_ID not found in environment variables."

    def upload_post(self, image_paths: List[str], caption: str):
        """
        Uploads an Instagram post using the Graph API.
        :param image_paths: List of paths to the image files to upload.
        :param caption: The caption for the Instagram post.
        """
        if len(image_paths) == 1:
            # Single image post
            media_id = self._create_image_container(image_paths[0], caption)
            assert media_id, "Failed to create image container."
        else:
            # Carousel post
            media_ids = [self._create_image_container(image_path) for image_path in image_paths]
            assert all(media_ids), "Failed to create one or more image containers for carousel."
            media_id = self._create_carousel_container(media_ids, caption)
            assert media_id, "Failed to create carousel container."

        # Publish the media
        self._publish_media(media_id)

    def _create_image_container(self, image_path: str, caption: str = '') -> str:
        """
        Creates an image media container.
        :param image_path: Path to the image file.
        :param caption: Caption for the image (optional).
        :return: Media container ID.
        """
        # Upload the image to a publicly accessible URL
        image_url = self._upload_image_to_server(image_path)
        assert image_url, f"Failed to upload image to server: {image_path}"

        media_url = f"{self.base_url}/{self.user_id}/media"
        payload = {
            'image_url': image_url,
            'caption': caption,
            'access_token': self.access_token
        }
        response = requests.post(media_url, data=payload)
        assert response.status_code == 200, f"Failed to create image container: {response.content}"
        media_id = response.json().get('id')
        assert media_id, f"No media ID returned for image container creation."
        return media_id

    def _create_carousel_container(self, media_ids: List[str], caption: str) -> str:
        """
        Creates a carousel media container.
        :param media_ids: List of child media container IDs.
        :param caption: Caption for the carousel post.
        :return: Carousel media container ID.
        """
        media_url = f"{self.base_url}/{self.user_id}/media"
        payload = {
            'media_type': 'CAROUSEL',
            'caption': caption,
            'children': ','.join(media_ids),
            'access_token': self.access_token
        }
        response = requests.post(media_url, data=payload)
        assert response.status_code == 200, f"Failed to create carousel container: {response.content}"
        media_id = response.json().get('id')
        assert media_id, f"No media ID returned for carousel container creation."
        return media_id

    def _publish_media(self, media_id: str):
        """
        Publishes the media container to Instagram.
        :param media_id: Media container ID.
        """
        publish_url = f"{self.base_url}/{self.user_id}/media_publish"
        payload = {
            'creation_id': media_id,
            'access_token': self.access_token
        }
        response = requests.post(publish_url, data=payload)
        assert response.status_code == 200, f"Failed to publish post: {response.content}"

    def _upload_image_to_server(self, image_path: str) -> str:
        """
        Uploads the image to AWS S3 and returns the image URL.
        """
        # Implement this method to upload your image to a server or cloud storage
        # For this example, we'll assume the image is already hosted and return the URL
        # Replace this with your actual implementation
        image_url = self._get_public_url(image_path)
        return image_url

    def _get_public_url(self, image_path: str) -> str:
        """
        Placeholder method to return the public URL of an image.
        :param image_path: Local path to the image file.
        :return: Publicly accessible URL of the image.
        """
        # Replace this with your actual implementation
        raise NotImplementedError("You need to implement image hosting to get a public URL.")

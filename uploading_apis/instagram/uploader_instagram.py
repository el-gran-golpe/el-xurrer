import os
import requests
from dotenv import load_dotenv

class InstagramUploader:
    def __init__(self):
        # Load the Instagram API token from the environment file
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'api_key_instagram.env')
        load_dotenv(env_path)
        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.base_url = "https://graph.instagram.com"

    def upload_post(self, image_path: str, caption: str):
        """
        Uploads an Instagram post using the Graph API.
        :param image_path: Path to the image file to upload.
        :param caption: The caption for the Instagram post.
        """
        # Step 1: Upload the image to Instagram
        image_url = self._upload_image(image_path)
        
        # Step 2: Publish the post with the uploaded image
        post_url = f"{self.base_url}/me/media"
        payload = {
            'image_url': image_url,
            'caption': caption,
            'access_token': self.access_token
        }
        response = requests.post(post_url, data=payload)
        if response.status_code == 200:
            print(f"Post successfully uploaded: {response.json()}")
        else:
            print(f"Failed to upload post: {response.content}")

    def _upload_image(self, image_path: str):
        # Logic for uploading the image to Instagram, possibly via a media container
        # Add your implementation for uploading images using Instagram's Graph API
        pass

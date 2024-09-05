# instagram_uploader.py
import requests
from loguru import logger

class InstagramAPI:
    def __init__(self, access_token):
        self.access_token = access_token

    def upload_image(self, image_urls, caption, location):
        logger.info(f"Uploading images: {image_urls}")

        # Step 1: Upload each image to Instagram to get media IDs
        media_ids = []
        for image_url in image_urls:
            upload_url = f"https://graph.instagram.com/v12.0/me/media"
            params = {
                "image_url": image_url,
                "caption": caption,
                "access_token": self.access_token
            }
            response = requests.post(upload_url, params=params)
            if response.status_code == 200:
                media_id = response.json()["id"]
                media_ids.append(media_id)
            else:
                logger.error(f"Failed to upload image: {response.text}")
                return None

        # Step 2: Publish the carousel post on Instagram
        publish_url = f"https://graph.instagram.com/v12.0/me/media_publish"
        publish_params = {
            "creation_id": ','.join(media_ids),
            "access_token": self.access_token
        }
        if location:
            publish_params["location"] = location

        publish_response = requests.post(publish_url, params=publish_params)
        if publish_response.status_code == 200:
            logger.info("Post published successfully.")
            return publish_response.json()
        else:
            logger.error(f"Failed to publish post: {publish_response.text}")
            return None

import os
import dotenv
import sys
# Add the parent directory of generation_tools to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from generation_tools.thumbnails_generator.imghippo import ImgHippo
import requests

META_API_KEY = os.path.join(os.path.dirname(__file__), 'api_key_instagram.env')

class GraphAPI:
    def __init__(self):
        dotenv.load_dotenv(META_API_KEY)

        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.user_id = os.getenv('INSTAGRAM_USER_ID')

        assert self.access_token, f"Instagram access token not found in {META_API_KEY}."
        assert self.user_id, f"Instagram user ID not found in {META_API_KEY}."

        # Base URL for Graph API
        self.base_url = "https://graph.facebook.com/v17.0"

    def upload_post(self, img_path: str, caption: str):
        # Step 1: Get image URL from ImgHippo
        img_hippo = ImgHippo()
        image_url = img_hippo.get_url_for_image(img_path)

        # Step 2: Create media container
        url = f"{self.base_url}/{self.user_id}/media"
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": self.access_token
        }
        response = requests.post(url, data=payload)
        response.raise_for_status()
        creation_id = response.json().get("id")

        # Step 3: Publish the media
        publish_url = f"{self.base_url}/{self.user_id}/media_publish"
        publish_payload = {
            "creation_id": creation_id,
            "access_token": self.access_token
        }
        publish_response = requests.post(publish_url, data=publish_payload)
        publish_response.raise_for_status()

        return publish_response.json()

# Example usage
if __name__ == "__main__":
    graph_api = GraphAPI()
    img_path = r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\rallying-the-troops\Rallying the Troops.png"
    caption = "Check out this amazing photo!"
    response = graph_api.upload_post(img_path, caption)
    print("Post published successfully:", response)

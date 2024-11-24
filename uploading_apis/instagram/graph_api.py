import os
import dotenv
from imghippo import ImgHippo

META_API_KEY = os.path.join(os.path.dirname(__file__), 'api_key_instagram.env')

class GraphAPI:
    def __init__(self):
        assert self.access_token, "Instagram access token not found at {META_API_KEY}."
        assert self.user_id, "Instagram user ID not found at {META_API_KEY}."

        dotenv.load_dotenv(META_API_KEY)

        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.user_id = os.getenv('INSTAGRAM_USER_ID')  
        self.base_url = "https://graph.facebook.com/v17.0"

      
    def upload_post(self):
        # Step 1: Get image URL from ImgHippo
        img_hippo = ImgHippo()
        image_url = img_hippo.get_url_for_image(img_path)
        # url = f"{self.base_url}/{self.user_id}/media"
        # headers = {}

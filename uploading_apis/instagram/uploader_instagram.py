import os
from dotenv import load_dotenv

class InstagramUploader:
    def __init__(self):
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'api_key_instagram.env')
        load_dotenv(env_path)
        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        self.user_id = os.getenv('INSTAGRAM_USER_ID')  # Add your Instagram user ID
        self.base_url = "https://graph.facebook.com/v17.0"

        # Ensure that necessary environment variables are loaded
        assert self.access_token, "INSTAGRAM_ACCESS_TOKEN not found in environment variables."
        assert self.user_id, "INSTAGRAM_USER_ID not found in environment variables."

    def upload_post(self):
        url = f"{self.base_url}/{self.user_id}/media"
        headers = {}
    



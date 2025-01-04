import sys
import os
import dotenv
import requests
# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from generation_tools.thumbnails_generator.imghippo import ImgHippo

META_API_KEY = os.path.join(os.path.dirname(__file__), 'api_key_instagram.env')

class GraphAPI:
    def __init__(self):
        dotenv.load_dotenv(META_API_KEY)
        self.account_id = os.getenv('INSTAGRAM_ACCOUNT_ID')
        self.user_access_token = os.getenv('USER_ACCESS_TOKEN')
        self.app_scoped_user_id = os.getenv('APP_SCOPED_USER_ID')
        assert self.account_id, f"Instagram account ID not found in {META_API_KEY}."
        assert self.user_access_token, f"Meta user access token not found in {META_API_KEY}."
        assert self.app_scoped_user_id, f"Meta app scoped user ID not found in {META_API_KEY}."
        self.base_url = "https://graph.facebook.com/v21.0"
        self.page_access_token = self._get_page_access_token()

    def _get_page_access_token(self):
        """Retrieve the Page Access Token using the User Access Token."""
        url = f"{self.base_url}/{self.app_scoped_user_id}/accounts"
        payload = {"access_token": self.user_access_token}
        
        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])
            
            # Iterate through all pages and return the first access_token found
            for page in pages:
                if "access_token" in page:
                    print(f"Retrieved Page Access Token for page: {page['name']}")
                    return page["access_token"]

            raise ValueError("No page found with the linked Instagram Business Account.")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while retrieving the Page Access Token: {e}")
            sys.exit(1)

    def upload_post(self, img_path: str, caption: str):
        assert img_path.lower().endswith('.jpeg'), "The image file must be a .jpeg"

        try:
            # Step 1: Get image URL from ImgHippo
            img_hippo = ImgHippo()
            image_url = img_hippo.get_url_for_image(img_path)

            # Step 2: Create media container
            url = f"{self.base_url}/{self.account_id}/media"
            payload = {
                "image_url": image_url,
                "caption": caption,
                "access_token": self.page_access_token
            }
            response = requests.post(url, data=payload)
            print(response.content)
            response.raise_for_status()
            creation_id = response.json().get("id")

            # Step 3: Publish the media
            publish_url = f"{self.base_url}/{self.account_id}/media_publish"
            publish_payload = {
                "creation_id": creation_id,
                "access_token": self.page_access_token
            }
            publish_response = requests.post(publish_url, data=publish_payload)
            publish_response.raise_for_status()
            

            return publish_response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return None

# Example usage
if __name__ == "__main__":
    graph_api = GraphAPI()
    img_path = r"C:\Users\Usuario\Downloads\image (3).jpeg"
    caption = "Check out this amazing photo!"
    response = graph_api.upload_post(img_path, caption)
    if response:
        print("Post published successfully:", response)
    else:
        print("Failed to publish post.")

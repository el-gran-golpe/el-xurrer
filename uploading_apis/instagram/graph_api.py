import sys
import os
import dotenv
import requests
import json
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
        self.page_id = self._get_page_id()

    def _get_page_id(self):
        """Retrieve the Page ID using the User Access Token."""
        url = f"{self.base_url}/{self.app_scoped_user_id}/accounts"
        payload = {"access_token": self.user_access_token}
        
        try:
            response = requests.get(url, params=payload)
            response.raise_for_status()
            pages = response.json().get("data", [])
            
            # Iterate through all pages and return the first page_id found
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
            
            # Iterate through all pages and return the first access_token found
            for page in pages:
                if "access_token" in page:
                    print(f"Retrieved Page Access Token for page: {page['name']}")
                    return page["access_token"]

            raise ValueError("No page found with the linked Instagram Business Account.")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while retrieving the Page Access Token: {e}")
            sys.exit(1)

    def upload_instagram_publication(self, img_path: str, caption: str):
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
        
    def upload_facebook_publication(self, img_paths: list, caption: str):
        """
        Uploads one or multiple images as a single post on the Facebook Page.
        
        Parameters:
        - img_paths (list): List of image paths to upload. Can be one or multiple images.
        - caption (str): Caption for the post.
        
        Returns:
        - dict: The response from the Facebook API if successful, None otherwise.
        """
        # Ensure img_paths is a list, even if a single image is provided
        if isinstance(img_paths, str):
            img_paths = [img_paths]

        media_ids = []

        # Step 1: Upload each photo as unpublished
        for img_path in img_paths:
            url = f"{self.base_url}/{self.page_id}/photos"
            files = {'source': open(img_path, 'rb')}
            data = {
                'published': 'false',  # Upload as unpublished media
                'access_token': self.page_access_token
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
            'attached_media': json.dumps(media_ids),
            'message': caption,
            'access_token': self.page_access_token
        }

        try:
            post_response = requests.post(post_url, data=post_data)
            post_response.raise_for_status()
            print("Post created successfully:", post_response.json())
            return post_response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while creating the post: {e}")
            return None

# Example usage
if __name__ == "__main__":
    graph_api = GraphAPI()
    img_paths = [
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_0.png",
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_1.png",
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_2.png"
    ]
    caption = "Emergency meeting time! 🗣️ I’m calling on my amazing team to brainstorm ideas. Together, we’ll find a way through this chaos! 💪"
    response = graph_api.upload_facebook_publication(img_paths, caption)
    #response = graph_api.upload_instagram_publication(img_path, caption)
  
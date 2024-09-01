import os
from functools import lru_cache

import requests
import dotenv

API_KEY_FILE = os.path.join(os.path.dirname(__file__), 'api_key.env')


class ImgHippo:
    def __init__(self):
        assert os.path.isfile(API_KEY_FILE), f"API key file not found at {API_KEY_FILE}"
        # Load environment variables from the .env file
        dotenv.load_dotenv(API_KEY_FILE)
        self.api_key = os.getenv('IMG_HIPPO_API_KEY')
        assert self.api_key is not None, "IMG_HIPPO_API_KEY is missing in the .env file"

    @lru_cache(maxsize=128)
    def get_url_for_image(self, img_path: str) -> str:
        assert os.path.isfile(img_path), f"Image file {img_path} does not exist"

        # Define the API endpoint
        url = "https://www.imghippo.com/v1/upload"

        # Prepare the file to be uploaded
        with open(img_path, 'rb') as img_file:
            files = {
                'file': img_file
            }
            data = {
                'api_key': self.api_key
            }

            # Make the POST request to upload the image
            response = requests.post(url, files=files, data=data)

        response.raise_for_status()
        assert response.status_code == 200, f"Failed to upload image: {response.text}"

        response_data = response.json()
        url = response_data['data']['view_url']
        return url



# Example usage
if __name__ == "__main__":
    img_hippo = ImgHippo()
    img_path = "./test.png"
    image_url = img_hippo.get_url_for_image(img_path)
    print(f"Uploaded image URL: {image_url}")

import os
from functools import lru_cache
import dotenv
import cloudscraper

API_KEY_FILE = os.path.join(os.path.dirname(__file__), "api_key.env")


class ImgHippo:
    def __init__(self):
        assert os.path.isfile(API_KEY_FILE), f"API key file not found at {API_KEY_FILE}"
        dotenv.load_dotenv(API_KEY_FILE)
        self.api_key = os.getenv("IMG_HIPPO_API_KEY")
        assert self.api_key is not None, "IMG_HIPPO_API_KEY is missing in the .env file"
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

    @lru_cache(maxsize=128)
    def get_url_for_image(self, img_path: str) -> str:
        assert os.path.isfile(img_path), f"Image file {img_path} does not exist"

        url = "https://api.imghippo.com/v1/upload"

        with open(img_path, "rb") as img_file:
            files = {"file": (os.path.basename(img_path), img_file, "image/jpeg")}

            data = {"api_key": self.api_key}

            response = self.scraper.post(url, files=files, data=data)

        # Debug information
        print("Request URL:", response.url)
        print("Status Code:", "\033[92m" + str(response.status_code) + "\033[0m")
        # print("Response Content:", response.text)

        response.raise_for_status()

        response_data = response.json()
        assert "data" in response_data and "view_url" in response_data["data"], (
            f"Unexpected response structure: {response_data}"
        )

        return response_data["data"]["view_url"]

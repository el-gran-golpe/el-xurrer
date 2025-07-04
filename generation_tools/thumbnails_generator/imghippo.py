from functools import lru_cache
from pathlib import Path

import cloudscraper
from loguru import logger
from pydantic import BaseSettings

API_KEY_FILE = Path(__file__).parent / "api_key.env"


class Settings(BaseSettings):
    IMG_HIPPO_API_KEY: str

    class Config:
        env_file = API_KEY_FILE
        env_file_encoding = "utf-8"


class ImgHippo:
    def __init__(self, settings: Settings = Settings()):
        # load & validate API key
        self.settings = settings
        self.api_key = self.settings.IMG_HIPPO_API_KEY

        # cloudscraper instance
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

        logger.debug("ImgHippo initialized")

    @lru_cache(maxsize=128)
    def get_url_for_image(self, img_path: Path) -> str:
        img_path = Path(img_path)

        url = "https://api.imghippo.com/v1/upload"
        with img_path.open("rb") as f:
            files = {"file": (img_path.name, f, "image/jpeg")}
            data = {"api_key": self.api_key}
            response = self.scraper.post(url, files=files, data=data)

        logger.info(f"Request URL: {response.url}")
        logger.info(f"Status Code: {response.status_code}")

        response.raise_for_status()
        payload = response.json()

        view_url = payload.get("data", {}).get("view_url")
        if not view_url:
            logger.error(f"Unexpected response: {payload}")
            raise ValueError(f"Unexpected response structure: {payload}")

        return view_url

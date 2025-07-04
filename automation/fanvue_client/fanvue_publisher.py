import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from pynput.keyboard import Controller, Key


load_dotenv(Path(__file__).parent / "fanvue_keys.env")


class FanvueCredentials(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    @classmethod
    def from_env(cls, alias: str) -> "FanvueCredentials":
        alias_norm = alias.strip().replace(" ", "_").upper()
        username = os.getenv(f"{alias_norm}_FANVUE_USERNAME")
        password = os.getenv(f"{alias_norm}_FANVUE_PASSWORD")
        try:
            return cls(username=username, password=password)
        except ValidationError as e:
            raise EnvironmentError(
                f"Invalid or missing Fanvue credentials for alias '{alias}': {e}"
            )


class FanvuePublisher:
    """
    Automates Fanvue actions (login, posting text, and uploading images)
    using SeleniumBase.
    """

    def __init__(self, driver):
        self.driver = driver
        self.driver.maximize_window()

    def login(self, alias: str):
        # Validate & load credentials
        creds = FanvueCredentials.from_env(alias)

        # Open the Fanvue login page and activate CDP mode
        self.driver.activate_cdp_mode("https://www.fanvue.com/signin")
        # Fill in username & password
        self.driver.type("input[name='email']", creds.username)
        self.driver.type("input[name='password']", creds.password)
        # Solve captcha & submit
        self.driver.uc_gui_click_captcha()
        self.driver.click("button[type='submit']")

    def post_publication(self, file_path: Path, caption: str):
        # Click "New Post" button
        self.driver.click("a[aria-label='New Post']")
        # Click "Upload from device" button
        self.driver.click("button[aria-label='Upload from device']")

        # Use keyboard to pick the file
        keyboard = Controller()
        keyboard.type(str(file_path))
        time.sleep(3)
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        time.sleep(1)

        # Add caption and create post
        self.driver.type("textarea[placeholder='Write a caption...']", caption)
        self.driver.click("//button[normalize-space(.//span)='Create post']")

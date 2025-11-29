import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from pynput.keyboard import Controller, Key
from selenium.common.exceptions import TimeoutException, WebDriverException

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
    Automates Fanvue basic actions (login and posting)
    using SeleniumBase.
    """

    HOME_PATH = "/home"

    def __init__(self, driver):
        self.driver = driver
        self.driver.maximize_window()

    def login(self, alias: str) -> None:
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

    def post_publication(self, file_path: Path, caption: str) -> None:
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

        # Wait for the post to be published (redirect to /home)
        self._wait_for_url(self.HOME_PATH, timeout=10.0, interval=0.5)

    def _wait_for_url(
        self, substring: str, timeout: float = 10.0, interval: float = 0.5
    ) -> None:
        """
        Poll self.driver.get_current_url() every `interval` seconds
        for up to `timeout` seconds until `substring` appears.
        Raises TimeoutException otherwise.
        """
        retries = int(timeout / interval)
        for _ in range(retries):
            try:
                current = self.driver.get_current_url()
            except WebDriverException:
                # Transient error reading URL; retry
                pass
            else:
                if substring in current:
                    return
            # stay in SeleniumBase’s session
            self.driver.sleep(interval)

        # Timed out without seeing the substring
        last = self.driver.get_current_url()
        raise TimeoutException(f"Post not published, still at: {last}")

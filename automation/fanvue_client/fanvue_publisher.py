import os
import sys
import time
import Path
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from pynput.keyboard import Controller, Key

load_dotenv(os.path.join(os.path.dirname(__file__), "fanvue_keys.env"))


class FanvuePublisher:
    """
    Automates Fanvue actions (login, posting text, and uploading images)
    using SeleniumBase.
    """

    def __init__(self, driver):
        self.driver = driver
        self.driver.maximize_window()

    def login(self, alias: str):
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias must be a non-empty string")
        alias_norm = alias.replace(" ", "_").upper()

        username = os.getenv(f"{alias_norm}_FANVUE_USERNAME")
        password = os.getenv(f"{alias_norm}_FANVUE_PASSWORD")
        if not username or not password:
            raise EnvironmentError(f"Missing credentials for alias '{alias}'")

        # Open the Fanvue login page and activate CDP mode for captcha handling
        self.driver.activate_cdp_mode("https://www.fanvue.com/signin")
        self.driver.type("input[name='email']", username)
        self.driver.type("input[name='password']", password)

        # Use SeleniumBase's built-in captcha click method
        self.driver.uc_gui_click_captcha()

        # Submit the login form
        self.driver.click("button[type='submit']")

    def post_publication(self, file_path: Path, caption: str):
        # Click "New Post" button
        self.driver.click("a[aria-label='New Post']")

        # Click "Upload from device" button
        self.driver.click("button[aria-label='Upload from device']")

        # Upload the corresponding images for the post
        keyboard = Controller()
        keyboard.type(str(file_path))
        time.sleep(3)
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        time.sleep(1)

        # Write the caption in the box
        self.driver.type("textarea[placeholder='Write a caption...']", caption)
        self.driver.click("//button[normalize-space(.//span)='Create post']")

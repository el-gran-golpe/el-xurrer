import os
import sys
from dotenv import load_dotenv
from seleniumbase import SB

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

load_dotenv(os.path.join(os.path.dirname(__file__), 'fanvue_keys.env'))

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
        #self.driver.open("https://www.fanvue.com/signin")
        self.driver.activate_cdp_mode("https://www.fanvue.com/signin")
        self.driver.type("input[name='email']", username)
        self.driver.type("input[name='password']", password)

        # Use SeleniumBase's built-in captcha click method
        self.driver.uc_gui_click_captcha()

        # Submit the login form
        self.driver.click("button[type='submit']")
        if self.driver.is_element_visible("//*[contains(text(), 'Dashboard')]"):
            print(f"Login successful for '{alias}' ({username})")
        else:
            print(f"Login failed for '{alias}'. Check credentials.")

    def post_publication(self, content: str):
        self.driver.open("https://www.fanvue.com/new-post")
        self.driver.type("textarea[name='postContent']", content)
        self.driver.click("button[type='submit']")
        if self.driver.is_element_visible("//*[contains(text(), 'Your post has been published')]"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

    def upload_picture(self, file_path: str):
        self.driver.open("https://www.fanvue.com/new-post")
        self.driver.choose_file("input[type='file']", file_path)
        self.driver.type("textarea[name='postContent']", "Here's an image!")
        self.driver.click("button[type='submit']")
        if self.driver.is_element_visible("//*[contains(text(), 'Your post has been published')]"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

if __name__ == "__main__":
    with SB(uc=True, test=True, locale_code="en") as driver:
        bot = FanvuePublisher(driver)
        bot.login("laura vigne")
        bot.post_publication("This is an automated post created by a bot!")
        bot.upload_picture("path/to/your/image.jpg")

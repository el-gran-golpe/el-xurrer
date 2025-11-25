import platform
import time
from pathlib import Path

from loguru import logger
from selenium.common.exceptions import TimeoutException, WebDriverException

from main_components.config import settings

# pynput keyboard automation only works reliably on Windows
if platform.system() == "Windows":
    from pynput.keyboard import Controller, Key

    PYNPUT_AVAILABLE = True
else:
    Controller = None
    Key = None
    PYNPUT_AVAILABLE = False
    logger.critical(
        f"FanvuePublisher file upload functionality requires pynput keyboard automation, "
        f"which is only supported on Windows. Current OS: {platform.system()}. "
        f"File upload via keyboard will not work.",
        RuntimeWarning,
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
        if not PYNPUT_AVAILABLE:
            return
        # Validate & load credentials
        creds = settings.get_fanvue_credentials(alias)

        # Open the Fanvue login page and activate CDP mode
        self.driver.activate_cdp_mode("https://www.fanvue.com/signin")
        # Fill in username & password
        self.driver.type("input[name='email']", creds.username)
        self.driver.type("input[name='password']", creds.password)
        # Solve captcha & submit
        self.driver.uc_gui_click_captcha()
        self.driver.click("button[type='submit']")

    def post_publication(self, file_path: Path, caption: str) -> None:
        if not PYNPUT_AVAILABLE:
            return

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

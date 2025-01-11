import asyncio
import random
from playwright.async_api import Playwright, async_playwright
from playwright_stealth import stealth_async
import os
from dotenv import load_dotenv
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from utils.bypass_captcha import detect_and_solve_captcha  

load_dotenv(os.path.join(os.path.dirname(__file__), 'fanvue_keys.env'))

class FanvuePublisher:
    """
    A bot to automate Fanvue actions such as logging in, creating a new post,
    or uploading pictures. 
    """

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self, headless: bool = False):
        # 1) Start Playwright
        self.playwright = await async_playwright().start()

        # 2) Launch the browser (chromium, firefox, or webkit)
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=["--start-maximized"]
        )

        # 3) Create the main context with a specific user agent and NO viewport
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            no_viewport=True,
        )

        # 4) Create a new page and apply stealth 
        self.page = await self.context.new_page() 
        #await stealth_async(self.page) 

    async def login(self, alias: str, screenshot_path: str, template_path: str):
        # Convert "laura vigne" --> "LAURA_VIGNE"
        assert isinstance(alias, str) and alias.strip(), "Alias must be a non-empty string"
        uppercase_alias = alias.strip().replace(' ', '_').upper()

        username_key = f"{uppercase_alias}_FANVUE_USERNAME"
        password_key = f"{uppercase_alias}_FANVUE_PASSWORD"

        username = os.getenv(username_key)
        password = os.getenv(password_key)

        assert username is not None, f"Environment variable {username_key} not found"
        assert password is not None, f"Environment variable {password_key} not found"

        # Go to the login page
        await self.page.goto("https://www.fanvue.com/signin", wait_until="networkidle")

        # Fill in the username and password fields
        await self.page.fill("input[name='email']", username)
        await self.page.fill("input[name='password']", password)

        # Detect and solve the CAPTCHA if present
        captcha_solved = await detect_and_solve_captcha(self.page, screenshot_path, template_path)
        if not captcha_solved:
            raise RuntimeError("[ERROR] Could not solve CAPTCHA. Exiting login.")

        # Click the login button
        await self.page.click("button[type='submit']")

        # Check if login was successful (e.g., "Dashboard" text is visible)
        if await self.page.is_visible("text=Dashboard"):
            print(f"Login successful for alias '{alias}'! ({username})")
        else:
            print(f"Login failed for alias '{alias}'. Check credentials.")

    async def post_publication(self, content: str):
        """Go to the new-post page, fill in content, and publish a text-only post."""
        await self.page.goto("https://www.fanvue.com/new-post", wait_until="networkidle")

        # Fill in the post content
        await self.page.fill("textarea[name='postContent']", content)

        # Submit the post
        await self.page.click("button[type='submit']")

        # Check for success
        if await self.page.is_visible("text=Your post has been published"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

    async def upload_picture(self, file_path: str):
        """Attach a file, optionally fill in text, and publish."""
        await self.page.goto("https://www.fanvue.com/new-post", wait_until="networkidle")

        # Upload the image
        await self.page.set_input_files("input[type='file']", file_path)

        # Optionally add some text content
        await self.page.fill("textarea[name='postContent']", "Here's an image!")

        # Submit the post
        await self.page.click("button[type='submit']")

        # Check for success
        if await self.page.is_visible("text=Your post has been published"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

    async def close(self):
        """Close the browser and stop Playwright."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


# ----------------- SAMPLE USAGE (for testing) -----------------
# If you run this file directly, it will perform an example workflow.
# Otherwise, you can import and use the FanvuePublisher class in your own code.

async def main():
    bot = FanvuePublisher()

    # Start the browser
    await bot.start(headless=False)

    # Example: login as "laura vigne"
    screenshot_path = os.path.join(os.path.dirname(__file__), 'page_screenshot.png')
    template_path = os.path.join(os.path.dirname(__file__), 'captcha_template.png')
    await bot.login("laura vigne", screenshot_path, template_path)


    # If that worked, let's do a post and upload a picture
    await bot.post_publication("This is an automated post created by a bot!")
    await bot.upload_picture("path/to/your/image.jpg")

    # Close
    await bot.close()

if __name__ == "__main__":
    asyncio.run(main())

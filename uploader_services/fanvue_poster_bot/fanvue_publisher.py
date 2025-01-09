import asyncio
import random
from playwright.async_api import async_playwright

class FanvuePublisher:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.browser = None
        self.context = None
        self.page = None

    async def human_delay(self):
        """Random delay to mimic human behavior."""
        await asyncio.sleep(random.uniform(0.5, 2.5))

    async def login(self):
        await self.page.goto("https://www.fanvue.com/login")
        await self.human_delay()

        # Fill in username
        await self.page.fill("input[name='username']", self.username)
        await self.human_delay()

        # Fill in password
        await self.page.fill("input[name='password']", self.password)
        await self.human_delay()

        # Click the login button
        await self.page.click("button[type='submit']")
        await self.human_delay()

        # Check if login was successful by looking for a specific dashboard element
        if await self.page.is_visible("text=Dashboard"):
            print("Login successful!")
        else:
            print("Login failed. Check credentials.")

    async def post_publication(self, content):
        await self.page.goto("https://www.fanvue.com/new-post")
        await self.human_delay()

        # Fill in the post content
        await self.page.fill("textarea[name='postContent']", content)
        await self.human_delay()

        # Submit the post
        await self.page.click("button[type='submit']")
        await self.human_delay()

        # Check if the post was submitted
        if await self.page.is_visible("text=Your post has been published"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

    async def upload_picture(self, file_path):
        await self.page.goto("https://www.fanvue.com/new-post")
        await self.human_delay()

        # Upload the image
        await self.page.set_input_files("input[type='file']", file_path)
        await self.human_delay()

        # Optionally add some text content
        await self.page.fill("textarea[name='postContent']", "Here's an image!")
        await self.human_delay()

        # Submit the post
        await self.page.click("button[type='submit']")
        await self.human_delay()

        # Check if the post was submitted
        if await self.page.is_visible("text=Your post has been published"):
            print("Post published successfully!")
        else:
            print("Failed to publish post.")

    async def start(self):
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=False)
            screen = await self.browser.evaluate("() => ({ width: window.screen.width, height: window.screen.height })")
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                viewport={"width": screen['width'], "height": screen['height']},
            )
            self.page = await self.context.new_page()

    async def close(self):
        if self.browser:
            await self.browser.close()

if __name__ == "__main__":
    async def main():
        bot = FanvuePublisher("your_username", "your_password")
        await bot.start()
        await bot.login()
        await bot.post_publication("This is an automated post created by a bot!")
        await bot.upload_picture("path/to/your/image.jpg")
        await bot.close()

    asyncio.run(main())

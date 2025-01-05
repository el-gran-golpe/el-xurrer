# Note: I hereby declare this class as deprecated because we have to pay for the basic tier in order to write and post stuff on X.

import tweepy
import os
import dotenv

# Load environment variables from .env file
API_KEY_PATH = os.path.join(os.path.dirname(__file__), 'api_key_x.env')
dotenv.load_dotenv(API_KEY_PATH)

class XAPI:
    def __init__(self):
        self.api_key = os.getenv('API_KEY')
        self.api_key_secret = os.getenv('API_KEY_SECRET')
        self.access_token = os.getenv('ACCESS_TOKEN')
        self.access_token_secret = os.getenv('ACCESS_TOKEN_SECRET')
        
        # Ensure all necessary credentials are loaded
        assert self.api_key, "API_KEY not found in environment variables."
        assert self.api_key_secret, "API_KEY_SECRET not found in environment variables."
        assert self.access_token, "ACCESS_TOKEN not found in environment variables."
        assert self.access_token_secret, "ACCESS_TOKEN_SECRET not found in environment variables."
        
        # Authenticate with the X API using tweepy
        auth = tweepy.OAuthHandler(self.api_key, self.api_key_secret)
        auth.set_access_token(self.access_token, self.access_token_secret)
        self.api = tweepy.API(auth)

    def post_tweet(self, message):
        """Post a simple text tweet."""
        if len(message) > 280:
            raise ValueError("Tweet exceeds the maximum allowed length of 280 characters.")
        try:
            response = self.api.update_status(message)
            print(f"Tweet posted successfully: {response.id}")
            return response
        except tweepy.TweepyException as e:
            print(f"Error posting tweet: {e}")
            return None

    def post_tweet_with_media(self, message, media_paths):
        """Post a tweet with attached images or videos.
        
        Parameters:
        - message (str): The text of the tweet.
        - media_paths (list): List of file paths to media (images or videos) to attach.
        """
        if len(message) > 280:
            raise ValueError("Tweet exceeds the maximum allowed length of 280 characters.")
        
        media_ids = []
        try:
            # Upload media and collect media IDs
            for media_path in media_paths:
                media = self.api.media_upload(media_path)
                media_ids.append(media.media_id)
                print(f"Uploaded media: {media_path}, ID: {media.media_id}")
            
            # Post tweet with media
            response = self.api.update_status(status=message, media_ids=media_ids)
            print(f"Tweet with media posted successfully: {response.id}")
            return response
        except tweepy.TweepyException as e:
            print(f"Error posting tweet with media: {e}")
            return None

if __name__ == "__main__":
    # Initialize the X API class
    x_api = XAPI()

    # Example: Post a simple text tweet
    message = "Let’s talk, my beautiful community! 💖 I want to hear your journeys toward authenticity—let's uplift each other! 😇"
    x_api.post_tweet(message)

    # Example: Post a tweet with media
    media_paths = [
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_0.png",
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_1.png",
        r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\resources\outputs\instagram_profiles\laura_vigne\posts\week_1\day_2\gathering-my-tribe_2.png"
    ]
    message_with_media = "Emergency meeting time! 🗣️ I’m calling on my amazing team to brainstorm ideas. Together, we’ll find a way through this chaos! 💪"    
    x_api.post_tweet_with_media(message_with_media, media_paths)

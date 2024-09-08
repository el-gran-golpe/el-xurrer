import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from loguru import logger
from datetime import datetime

API_SECRETS_FILE = os.path.join(os.path.dirname(__file__), 'youtube-api-secret.json')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), 'token.json')
SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly']


class YoutubeAPI:
    def __init__(self):
        assert os.path.isfile(API_SECRETS_FILE), f"API secrets file not found: {API_SECRETS_FILE}"
        self.creds = None
        self._authenticate()
        self._categories = None

    @property
    def categories(self):
        if self._categories is None:
            self._categories = self.get_video_categories()
        return self._categories

    def _authenticate(self):
        # Load credentials from token file if it exists
        if os.path.exists(TOKEN_FILE):
            self.creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        # If no valid credentials, go through the OAuth flow
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(API_SECRETS_FILE, SCOPES)
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(TOKEN_FILE, 'w') as token:
                token.write(self.creds.to_json())

    def list_channels(self):
        try:
            youtube = build('youtube', 'v3', credentials=self.creds)
            request = youtube.channels().list(
                part='snippet,contentDetails,statistics',
                mine=True
            )
            response = request.execute()

            channels = None
            if 'items' in response and response['items']:
                channels = {channel['snippet']['title']:
                    {
                        'id': channel['id'],
                        'name': channel['snippet']['title'],
                        'description': channel['snippet']['description'],
                        'custom_url': channel['snippet'].get('customUrl', 'N/A'),
                        'thumbnail': channel['snippet']['thumbnails']['high']['url'],
                        'subscribers': channel['statistics'].get('subscriberCount', 'N/A'),
                        'views': channel['statistics'].get('viewCount', 'N/A'),
                        'videos': channel['statistics'].get('videoCount', 'N/A'),
                    } for channel in response['items']}
            else:
                logger.error("No channels found.")

            return channels

        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return None

    def list_videos(self, max_results=10):
        try:
            youtube = build('youtube', 'v3', credentials=self.creds)

            # First, get the channel details to find the "uploads" playlist ID
            channels_response = youtube.channels().list(
                part="contentDetails,snippet",
                mine=True
            ).execute()

            # Extract the uploads playlist ID
            uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # Now, retrieve the videos from the uploads playlist
            playlist_items_response = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=max_results
            ).execute()

            videos = {}
            if 'items' in playlist_items_response and playlist_items_response['items']:
                for item in playlist_items_response['items']:
                    video_id = item['contentDetails']['videoId']

                    # Get detailed video info for each video
                    video_response = youtube.videos().list(
                        part="snippet,statistics",
                        id=video_id
                    ).execute()

                    if 'items' in video_response and video_response['items']:
                        video = video_response['items'][0]
                        title = video['snippet']['title']
                        videos[title] = {
                            'id': video_id,
                            'title': title,
                            'description': video['snippet']['description'],
                            'published_at': video['snippet']['publishedAt'],
                            'thumbnail': video['snippet']['thumbnails']['high']['url'],
                            'views': video['statistics'].get('viewCount'),
                            'likes': video['statistics'].get('likeCount'),
                            'comments': video['statistics'].get('commentCount'),
                        }
                if not videos:
                    logger.error("No videos found.")
            else:
                logger.error("No playlist items found.")

            return videos

        except HttpError as error:
            logger.error(f"An error occurred while listing videos: {error}")
            return None

    def upload_video(self, video_file_path: str, title: str, description: str, tags=None,
                     category: str = 'Education', lang: str = 'es',
                     on_behalf_of_content_owner=None,
                     on_behalf_of_content_owner_channel=None):

        assert os.path.isfile(video_file_path), f"Video file not found: {video_file_path}"
        already_uploaded_videos = self.list_videos()
        assert title not in already_uploaded_videos, f"Video with title '{title}' already exists."

        # Get video categories to find the category ID
        categories = self.get_video_categories(region_code='ES')
        assert category.lower() in categories, f"Category '{category}' not found."
        # Get the category ID for the current_category
        category_id = categories[category.lower()]

        now = datetime.now()
        recording_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")


        youtube = build('youtube', 'v3', credentials=self.creds)

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags or [],
                'categoryId': category_id,
                'defaultLanguage': lang
            },
            'status': {
                'privacyStatus': 'public',
                'embeddable': True,
                'license': 'youtube',
                'publicStatsViewable': True,
                'publishAt': None,  # Publish immediately
                'selfDeclaredMadeForKids': False,
            },
            'recordingDetails': {
                'recordingDate': recording_date
            }
        }

        # MediaFileUpload object to manage the file to be uploaded
        media = MediaFileUpload(video_file_path, chunksize=-1, resumable=True)

        # Insert the video
        request = youtube.videos().insert(
            part="snippet,status,recordingDetails",
            body=body,
            media_body=media,
            notifySubscribers=True,
        )

        response = request.execute()

        logger.info(f"Video uploaded successfully: https://www.youtube.com/watch?v={response['id']}")
        return response

    def get_video_categories(self, region_code='ES'):
        """
        Fetches the video categories available on YouTube.

        Parameters:
        - region_code (str): The region code for which to fetch video categories. Default is Spain

        Returns:
        - dict: A dictionary mapping category IDs to category titles.
        """
        try:
            youtube = build('youtube', 'v3', credentials=self.creds)
            request = youtube.videoCategories().list(
                part="snippet",
                regionCode=region_code
            )
            response = request.execute()

            categories = {item['snippet']['title'].lower(): item['id'] for item in response['items']}
            return categories

        except HttpError as error:
            logger.error(f"An error occurred while fetching video categories: {error}")
            return None


if __name__ == '__main__':
    youtube_api = YoutubeAPI()

    # List channels (example usage)
    channels = youtube_api.list_channels()
    print(json.dumps(channels, indent=4, ensure_ascii=True))

    # List videos (example usage)
    videos = youtube_api.list_videos(max_results=50)
    print(json.dumps(videos, indent=4, ensure_ascii=True))

    get_video_categories = youtube_api.get_video_categories()
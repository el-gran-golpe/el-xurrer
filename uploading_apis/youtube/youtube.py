import requests
import webbrowser
import json
from loguru import logger
import os
from utils.one_request_server import OneRequestServer

API_SECRETS_FILE = os.path.join(os.path.dirname(__file__), 'youtube-api-secret.json')

# Configuration
PORT = 9004
REDIRECT_URI = f'http://127.0.0.1:{PORT}/'
SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
AUTH_URI = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'

class YoutubeAPI:
    def __init__(self):
        assert os.path.isfile(API_SECRETS_FILE), f"API secrets file not found: {API_SECRETS_FILE}"
        with open(API_SECRETS_FILE, 'r') as f:
            api_secrets = json.load(f)
            self.client_id = api_secrets['installed']['client_id']
            self.client_secret = api_secrets['installed']['client_secret']
            self._token = None

    @property
    def token(self):
        if self._token is None:
            auth_url = self._get_authorization_url()
            logger.info(f"Please go to this URL and authorize the application: {auth_url}")
            webbrowser.open(auth_url)

            with OneRequestServer(port=PORT) as server:
                params = server.wait_for_request()

            auth_code = params['code'][0]
            self._token = self._exchange_code_for_token(auth_code)

        return self._token

    def _get_authorization_url(self, scope=SCOPE):
        params = {
            'scope': scope,
            'response_type': 'code',
            'redirect_uri': REDIRECT_URI,
            'client_id': self.client_id,
            'access_type': 'offline',
            'include_granted_scopes': 'true'
        }
        url = f"{AUTH_URI}?{requests.compat.urlencode(params)}"
        return url

    def _exchange_code_for_token(self, auth_code):
        data = {
            'code': auth_code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        response = requests.post(TOKEN_URI, data=data)
        response_data = response.json()
        if response.status_code == 200:
            return response_data['access_token']
        else:
            print(f"Error: {response_data}")
            return None

    def list_channels(self):
        url = 'https://www.googleapis.com/youtube/v3/channels'
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/json'
        }
        params = {
            'part': 'snippet,contentDetails,statistics',
            'mine': 'true'
        }
        response = requests.get(url, headers=headers, params=params)
        channels = None
        if response.status_code == 200:
            data = response.json()
            if 'items' in data and data['items']:
                channels = {channel['snippet']['title'] :
                    {
                        'id': channel['id'],
                        'name': channel['snippet']['title'],
                        'description': channel['snippet']['description'],
                        'custom_url': channel['snippet']['customUrl'],
                        'thumbnail': channel['snippet']['thumbnails']['high']['url'],

                        'subscribers': channel['statistics']['subscriberCount'],
                        'views': channel['statistics']['viewCount'],
                        'videos': channel['statistics']['videoCount'],
                    } for channel in data['items']}

            else:
                logger.error("No channels found.")
        else:
            logger.error(f"Failed to retrieve channels: {response.status_code}")
            logger.error(response.json())

        return channels

if __name__ == '__main__':
    youtube_api = YoutubeAPI()
    channels = youtube_api.list_channels()

    print(channels)

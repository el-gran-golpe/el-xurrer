import requests
import random
import os
import dotenv
from PIL import Image

from generation_tools.thumbnails_generator.constants import TEMPLATES_BY_API_KEY
from generation_tools.thumbnails_generator.imghippo import ImgHippo

API_KEY_FILE = os.path.join(os.path.dirname(__file__), 'api_key.env')

class Templated:
    def __init__(self):
        assert os.path.isfile(API_KEY_FILE), f"API key file not found at {API_KEY_FILE}"
        # Load environment variables from the .env file
        dotenv.load_dotenv(API_KEY_FILE)
        assert all(os.getenv(api_key) is not None for api_key in TEMPLATES_BY_API_KEY.keys()), \
            "Some API keys are missing in the .env file"

        self.url_generator = ImgHippo()
    def generate_thumbnail(self, text: str, image: str, output_path: str):
        assert os.path.isfile(image), f"Image file {image} does not exist"
        # Get a random API key name and the corresponding template ID
        api_key_name = random.choice(list(TEMPLATES_BY_API_KEY.keys()))
        template_id = random.choice(TEMPLATES_BY_API_KEY[api_key_name])

        # Get the actual API key value from the environment variable
        api_key = os.getenv(api_key_name)

        if not api_key:
            raise ValueError(f"API key for '{api_key_name}' not found in environment variables")
        image_url = self.url_generator.get_url_for_image(img_path=image)
        # Define the payload for the POST request
        payload = {
            "template": template_id,
            "layers": {
                "text": {
                    "text": text
                },
                "image": {
                    "image_url": image_url
                }
            }
        }

        # Make the POST request to the templated.io API
        response = requests.post(
            url='https://api.templated.io/v1/render',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            },
            json=payload
        )

        response.raise_for_status()
        assert response.status_code == 200, f"Failed to generate thumbnail: {response.text}"
        # Check if the request was successful
        url = response.json()['render_url']

        # Read it with PIL and save it
        img = Image.open(requests.get(url, stream=True).raw)
        img.save(output_path)
        return output_path

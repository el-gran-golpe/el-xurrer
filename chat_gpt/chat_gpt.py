import os
from openai import OpenAI
import json
import time
from dotenv import load_dotenv
from tqdm import tqdm

from utils.utils import get_closest_monday

ENV_FILE = os.path.join(os.path.dirname(__file__), 'api_key.env')

class ChatGPT:
    def __init__(self, base_model="gpt-4o-mini"):
        assert os.path.isfile(ENV_FILE), (f"Missing API key file: {ENV_FILE}. "
                                          f"This file should have the following format:\n"
                                            f"OPENAI_API_KEY=<your-api-key>")
        # Load the API key from the api_key.env file
        load_dotenv(ENV_FILE)

        self.client = OpenAI(
            # This is the default and can be omitted
            api_key=os.getenv('OPENAI_API_KEY'),
        )

        self.base_model = base_model

    def generate_script(self, prompt_template_path: str, theme_prompt: str, thumbnail_text: str,
                        title: str, duration: int = 5, lang: str= 'en', base_model: str = None) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(duration, (int, float)) and duration > 0, "Duration must be a positive number"
        # Load the prompt template JSON file
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        assert lang in prompt_template, f"Language '{lang}' not found in the prompt template file"

        # Retrieve the list of prompts for the specified language
        prompts = prompt_template[lang]

        assert isinstance(prompt_template[lang], list), f"Prompts for language '{lang}' must be a list"
        assert len(prompts) > 0, f"No prompts found for language '{lang}' in the prompt template file"

        # Format the first prompt
        prompts[0] = prompts[0].format(duration=duration, prompt=theme_prompt)
        prompts[2] = prompts[2].format(thumbnail_text=thumbnail_text)
        prompts[3] = prompts[3].replace('{thumbnail_text}', thumbnail_text).replace('{title}', title)

        return self._generate_dict_from_prompts(prompts=prompts, base_model = base_model, desc="Generating script")

    def generate_youtube_planing(self, prompt_template_path: str, video_count: int, lang: str= 'en',
                                 base_model: str = None) -> dict:
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(video_count, int) and video_count > 0, "Videos count must be a positive integer"
        # Load the prompt template JSON file
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        assert lang in prompt_template, f"Language '{lang}' not found in the prompt template file"

        # Retrieve the list of prompts for the specified language
        prompts = prompt_template[lang]

        assert isinstance(prompt_template[lang], list), f"Prompts for language '{lang}' must be a list"
        assert len(prompts) > 0, f"No prompts found for language '{lang}' in the prompt template file"
        monday_date = get_closest_monday().strftime('%Y-%m-%d')
        assert lang in ('en', 'es'), "Language must be 'en' or 'es'"
        monday = 'Lunes' if lang == 'es' else 'Monday'

        prompts[0] = prompts[0].format(video_count=video_count)
        prompts[1] = prompts[1].format(day_of_week=monday, date=monday_date)
        # Initialize the conversation history
        planning = self._generate_dict_from_prompts(prompts=prompts, base_model = base_model,
                                                    desc="Generating planning")
        return planning

    def _generate_dict_from_prompts(self, prompts, base_model: str = None, desc: str = "Generating") -> dict:
        if base_model is None:
            base_model = self.base_model
        assert isinstance(base_model, str), "Base model must be a string"
        # Initialize the conversation history
        conversation = []
        # Loop through each prompt and get a response
        for i, user_prompt in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            # Append the user's prompt to the conversation
            conversation.append({"role": "user", "content": user_prompt})

            # Get the assistant's response
            response = self.client.chat.completions.create(
                model=base_model,
                messages=conversation,
                max_tokens=4096
            )

            # Extract the assistant's reply
            assistant_reply = response.choices[0].message.content

            # Append the assistant's reply to the conversation
            conversation.append({"role": "assistant", "content": assistant_reply})

            # Pause between requests to avoid hitting rate limits
            time.sleep(1)
        # The last message contains a json object with the script
        last_message = conversation[-1]["content"]
        # Decode the JSON object
        output_dict = self.decode_json_from_message(last_message)
        return output_dict



    def decode_json_from_message(self, message: str) -> dict:
        if message.startswith('```json'):
            assert message.endswith('```'), f"JSON message must end with '```' but got:\n{message}"
            message = message[len('```json'): -len('```')]
        try:
            # Remove the leading and trailing quotes
            message = message.strip('"')
            # Decode the JSON object
            return json.loads(message)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON object: {e}")
            return {}




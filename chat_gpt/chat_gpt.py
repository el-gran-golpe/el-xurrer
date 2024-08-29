import os
from openai import OpenAI
import json
import time
from dotenv import load_dotenv
from tqdm import tqdm

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

    def generate_script(self, prompt_template_path: str, prompt: str, duration: int=5, lang: str='en') -> dict:

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
        prompts[0] = prompts[0].format(duration=duration, prompt=prompt)

        # Initialize the conversation history
        conversation = []

        # Loop through each prompt and get a response
        for i, user_prompt in tqdm(enumerate(prompts), desc="Generating script", total=len(prompts)):
            # Append the user's prompt to the conversation
            conversation.append({"role": "user", "content": user_prompt})

            # Get the assistant's response
            response = self.client.chat.completions.create(
                model=self.base_model,
                messages=conversation
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
        script = self.decode_json_from_message(last_message)

        return script


    def decode_json_from_message(self, message: str) -> dict:
        if message.startswith('```json'):
            assert message.endswith('```'), "JSON message must end with '```'"
            message = message[len('```json'): -len('```')]
        try:
            # Remove the leading and trailing quotes
            message = message.strip('"')
            # Decode the JSON object
            return json.loads(message)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON object: {e}")
            return {}




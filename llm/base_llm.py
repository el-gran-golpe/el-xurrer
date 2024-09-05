import os
import random
from copy import deepcopy
import json
import time
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, Stream
from openai.types.chat import ChatCompletionChunk, ChatCompletion
from tqdm import tqdm
from loguru import logger

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage, StreamingChatCompletionsUpdate, ChatCompletions, AssistantMessage
from azure.core.credentials import AzureKeyCredential

from llm.constants import MODEL_BY_BACKEND, AZURE, OPENAI
from utils.utils import get_closest_monday

ENV_FILE = os.path.join(os.path.dirname(__file__), 'api_key.env')


class BaseLLM:
    def __init__(self, preferred_models: list[str]|str=("Mistral-large",)):
        assert os.path.isfile(ENV_FILE), (f"Missing API key file: {ENV_FILE}. "
                                          f"This file should have the following format:\n"
                                          f"GITHUB_API_KEY=<your-api-key>")
        # Load the API key from the api_key.env file
        load_dotenv(ENV_FILE)
        if isinstance(preferred_models, str):
            preferred_models = [preferred_models]

        self.preferred_models = preferred_models
        self.api_keys = {
            'GITHUB': os.getenv('GITHUB_API_KEY_HARU'),
            'OPENAI': os.getenv('OPENAI_API_KEY'),
        }

        self.exhausted_models = []
        self.client, self.active_backend = None, None
    def get_client(self, model: str):
        assert model in MODEL_BY_BACKEND, f"Model not found: {model}"
        backend = MODEL_BY_BACKEND[model]
        if self.active_backend == backend and self.client is not None:
            return self.client

        if backend == OPENAI:
            return self.get_new_client_openai()
        elif backend == AZURE:
            return self.get_new_client_azure()
        else:
            raise NotImplementedError(f"Backend not implemented: {backend}")

    def get_new_client_azure(self):
        github_api_key = self.api_keys['GITHUB']
        assert len(github_api_key) > 0, "Missing GITHUB_API_KEY for Azure authentication"
        github_api_key = random.choice(github_api_key)
        if github_api_key:
            self.client = ChatCompletionsClient(
                endpoint="https://models.inference.ai.azure.com",
                credential=AzureKeyCredential(github_api_key)
            )
        self.active_backend = AZURE
        return self.client

    def get_new_client_openai(self):
        # First of all, try to use the GitHub API key if available (Is free)
        github_api_keys = self.api_keys['GITHUB']
        base_url = "https://models.inference.ai.azure.com" if len(github_api_keys) > 0 else None
        api_key = random.choice(github_api_keys) if len(github_api_keys) > 0 else self.api_keys['OPENAI']

        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key
        )

        self.active_backend = OPENAI
        return self.client


    def _generate_dict_from_prompts(self, prompts, preferred_model: list = None, desc: str = "Generating",
                                    system_prompt: str | None = None, improvement_prompts: list | tuple = (),
                                    force_models: dict = {}) -> dict:

        if preferred_model is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        conversation = []
        if system_prompt:
            conversation.append({"role": "system", "content": system_prompt})

        # Loop through each prompt and get a response
        for i, user_prompt in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            # Append the user's prompt to the conversation
            conversation.append({"role": "user", "content": user_prompt})
            models = preferred_models if i not in force_models else force_models[i]
            # Get the assistant's response
            assistant_reply, finish_reason = self.get_stream_response(conversation=conversation, preferred_models=models)

            # If it was an improvement prompt, remove the previous message and answer
            if i in improvement_prompts:
                improvement_prompt = conversation.pop()
                assert improvement_prompt["role"] == "user", "Improvement prompt must be a user prompt"
                worse_answer = conversation.pop()
                assert worse_answer["role"] == "assistant", "Worse answer must be an assistant answer"
            # Append the assistant's reply to the conversation
            conversation.append({"role": "assistant", "content": assistant_reply})

            # Pause between requests to avoid hitting rate limits
            time.sleep(1)

        # The last message contains a json object with the script
        last_message = conversation[-1]["content"]
        # Decode the JSON object
        output_dict = self.decode_json_from_message(last_message)
        return output_dict


    def get_stream_response(self, conversation: list[dict], preferred_models: list = None, verbose: bool = True) -> tuple:

        if preferred_models is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        stream = self.__get_response_stream(conversation=conversation, preferred_models=preferred_models)

        assistant_reply, finish_reason = "", None
        for chunk in stream:
            current_finish_reason = chunk.choices[0].finish_reason
            new_content = chunk.choices[0].delta.content
            if new_content is not None:
                assistant_reply += new_content
                if verbose:
                    print(new_content, end="")
            if current_finish_reason is not None:
                finish_reason = current_finish_reason

        assert finish_reason is not None, "Finish reason not found"
        if finish_reason == "length":
            continue_conversation = deepcopy(conversation)
            continue_conversation.append({"role": "assistant", "content": assistant_reply})
            continue_conversation.append({"role": "user", "content": "Continue EXACTLY where we left off"})
            new_assistant_reply, finish_reason = self.__get_response_stream(conversation=continue_conversation,
                                                                            preferred_models=preferred_models)
            assistant_reply += new_assistant_reply

        return assistant_reply, finish_reason

    def __get_response_stream(self, conversation: list[dict], preferred_models: list) -> (
            Iterable[StreamingChatCompletionsUpdate] | ChatCompletions | Stream[ChatCompletionChunk] | ChatCompletion):
        # Select the best model
        preferred_models = [model for model in preferred_models if model not in self.exhausted_models]
        assert len(preferred_models) > 0, "No models available"
        model = preferred_models[0]
        self.client = self.get_client(model=model)
        if self.active_backend == AZURE:
            stream = self.client.complete(
                messages=self.conversation_to_azure_format(conversation=conversation),
                model=model,
                stream=True
            )
        elif self.active_backend == OPENAI:
            try:
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=conversation,
                    stream=True
                )
            except APIStatusError as e:
                error_code, error_message = e.code, e.message
                if error_code == "tokens_limit_reached":
                    raise NotImplementedError("Tokens limit reached, we'll have to change the model")
                    # Move to a different model
                else:
                    raise NotImplementedError(f"Error: {error_code} - {error_message}")
        else:
            raise NotImplementedError(f"Backend not implemented: {self.active_backend}")

        return stream


    def conversation_to_azure_format(self, conversation: list[dict]) -> list:

        azure_conversation = []
        for message in conversation:
            assert "content" in message and "role" in message, f"Invalid message format: {message}"
            content, role = message["content"], message["role"]
            if role == "user":
                message = UserMessage(content=content)
            elif role == "assistant":
                message = AssistantMessage(content=content)
            elif role == "system":
                message = SystemMessage(content=content)
            else:
                raise ValueError(f"Invalid role: {role}")
            azure_conversation.append(message)
        return azure_conversation

    def decode_json_from_message(self, message: str) -> dict:
        if message.startswith('```json'):
            message = message[len('```json'): -len('```')]
            message = message.replace('\n```json', '').replace('```json\n', '').replace('```json', '')

        message = message.strip('"')
        return json.loads(message)

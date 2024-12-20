import os
import random
from copy import deepcopy
import json
import re
from typing import Iterable

from azure.core.exceptions import HttpResponseError
from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, Stream
from openai.types.chat import ChatCompletionChunk, ChatCompletion
from tqdm import tqdm
from loguru import logger

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage, StreamingChatCompletionsUpdate, ChatCompletions, AssistantMessage
from azure.core.credentials import AzureKeyCredential

from llm.constants import MODEL_BY_BACKEND, AZURE, OPENAI, PREFERRED_PAID_MODELS, DEFAULT_PREFERRED_MODELS, \
    CANNOT_ASSIST_PHRASES, INCOMPLETE_OUTPUT_PHRASES
from utils.utils import get_closest_monday

ENV_FILE = os.path.join(os.path.dirname(__file__), 'api_key.env')


class BaseLLM:
    def __init__(self, preferred_models: list[str]|str=DEFAULT_PREFERRED_MODELS):
        assert os.path.isfile(ENV_FILE), (f"Missing API key file: {ENV_FILE}. "
                                          f"This file should have the following format:\n"
                                          f"GITHUB_API_KEY=<your-api-key>")
        # Load the API key from the api_key.env file
        load_dotenv(ENV_FILE)
        if isinstance(preferred_models, str):
            preferred_models = [preferred_models]

        self.preferred_models = preferred_models
        self.api_keys = {
            'GITHUB': [os.getenv('GITHUB_API_KEY_HARU')],
            'OPENAI': os.getenv('OPENAI_API_KEY'),
        }

        self.exhausted_models = []
        self.client, self.active_backend = None, None
        self.using_paid_api = False
    def get_client(self, model: str, paid_api: bool = False):
        assert model in MODEL_BY_BACKEND, f"Model not found: {model}"
        backend = MODEL_BY_BACKEND[model]
        if paid_api:
            assert backend == OPENAI, "Paid API is only available for OpenAI models"

        if (self.active_backend == backend and self.client is not None
                and self.using_paid_api == paid_api):
            return self.client

        if backend == OPENAI:
            return self.get_new_client_openai(paid_api=paid_api)
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
        self.using_paid_api = False
        return self.client

    def get_new_client_openai(self, paid_api: bool = False):
        # First of all, try to use the GitHub API key if available (Is free)
        if not paid_api:
            assert len(self.api_keys['GITHUB']) > 0, "No GitHub API keys found"
            api_key, base_url = random.choice(self.api_keys['GITHUB']), "https://models.inference.ai.azure.com"
        else:
            assert self.api_keys['OPENAI'] is not None, "No OpenAI API key found"
            api_key, base_url = self.api_keys['OPENAI'], None

        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key
        )

        self.active_backend = OPENAI
        self.using_paid_api = paid_api
        return self.client

    def _update_conversation_before_model_pass(self, conversation_history: list[dict], new_user_message: str, step: int = None) -> list[dict]:
        conversation = deepcopy(conversation_history)
        conversation.append({"role": "user", "content": new_user_message})
        return conversation

    def _update_conversation_after_model_pass(self, conversation_history: list[dict], output_assistant_message: str,
                                              step: int = None) -> list[dict]:
        conversation = deepcopy(conversation_history)
        conversation.append({"role": "assistant", "content": output_assistant_message})
        return conversation

    def _generate_dict_from_plain_string_prompts(self, prompts, preferred_models: list = None, desc: str = "Generating",
                                    system_prompt: str | None = None) -> dict:

        if preferred_models is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        conversation = []
        if system_prompt:
            conversation.append({"role": "system", "content": system_prompt})

        # Loop through each prompt and get a response
        for i, user_prompt in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            # Append the user's prompt to the conversation
            conversation = self._update_conversation_before_model_pass(conversation_history=conversation,
                                                                       new_user_message=user_prompt, step=i)
            # Get the assistant's response
            assistant_reply, finish_reason = self.get_model_response(conversation=conversation,
                                                                     preferred_models=preferred_models)

            # If it was an improvement prompt, remove the previous message and answer
            # Append the assistant's reply to the conversation
            conversation = self._update_conversation_after_model_pass(conversation_history=conversation,
                                                                      output_assistant_message=assistant_reply, step=i)

        # The last message contains a json object with the script
        last_message = conversation[-1]["content"]
        # Decode the JSON object
        output_dict = self.decode_json_from_message(last_message)
        return output_dict


    def get_model_response(self, conversation: list[dict], preferred_models: list = None, verbose: bool = True,
                           structured_json: dict[str, str|dict[str]]|None = None) -> tuple:

        if preferred_models is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        stream = self.__get_response_stream(conversation=conversation, preferred_models=preferred_models,
                                            structured_json=structured_json)

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

        # TODO: That's for non-gpt models that seems to not return a finish reason
        model = [model for model in preferred_models if model not in self.exhausted_models][0]
        if not model.startswith("gpt-") and finish_reason is None:
            logger.debug(f"Model {model} did not return a finish reason. Assuming stop")
            finish_reason = "stop"

        assert finish_reason is not None, "Finish reason not found"
        if any(phrase.lower() in assistant_reply.lower() for phrase in INCOMPLETE_OUTPUT_PHRASES):
            # Remove al of them from the assistant reply with a regex
            assistant_reply = re.sub("|".join(INCOMPLETE_OUTPUT_PHRASES), "", assistant_reply, flags=re.IGNORECASE)
            finish_reason = "length"
            logger.warning("Assistant reply is incomplete. Retrying with the same conversation")

        if finish_reason == "length":
            continue_conversation = deepcopy(conversation)
            continue_conversation.append({"role": "assistant", "content": assistant_reply})
            continue_conversation.append({"role": "user", "content": "Continue EXACTLY where we left off"})
            new_assistant_reply, finish_reason = self.get_model_response(conversation=continue_conversation,
                                                                        preferred_models=preferred_models)
            assistant_reply += new_assistant_reply

        elif finish_reason == 'content_filter':
            print()
            logger.debug("Content filter triggered. Retrying with a different model")
            assert len(preferred_models) > 1, "No more models to try"
            assistant_reply, finish_reason = self.get_model_response(conversation=conversation, preferred_models=preferred_models[1:])

        assert finish_reason == "stop", f"Unexpected finish reason: {finish_reason}"
        return assistant_reply, finish_reason

    def __get_response_stream(self, conversation: list[dict], preferred_models: list,
                              use_paid_api: bool = False, structured_json: dict[str, str|dict[str]]|None = None) -> (
            Iterable[StreamingChatCompletionsUpdate] | ChatCompletions | Stream[ChatCompletionChunk] | ChatCompletion):
        # Select the best model that is not exhausted
        if not use_paid_api:
            preferred_models = [model for model in preferred_models if model not in self.exhausted_models]
        assert len(preferred_models) > 0, "No models available"
        model = preferred_models[0]

        self.client = self.get_client(model=model, paid_api=use_paid_api)

        try:
            if self.active_backend == AZURE:
                stream = self.client.complete(
                    messages=self.conversation_to_azure_format(conversation=conversation),
                    model=model,
                    stream=True
                )
            elif self.active_backend == OPENAI:
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=conversation,
                    stream=True
                )
            else:
                raise NotImplementedError(f"Backend not implemented: {self.active_backend}")
        except (APIStatusError, HttpResponseError) as e:
            if isinstance(e, APIStatusError):
                error_code, error_message = e.code, e.message
            elif isinstance(e, HttpResponseError):
                error_code, error_message = e.error.code, e.error.message
            else:
                raise e

            if error_code == "tokens_limit_reached":
                # Context token limit reached. So we'll have to move to the OpenAI paid API for this
                assert not use_paid_api, "This error should not happen when using the paid API"
                print()
                logger.warning(f"Request size exceeded free github API limit. Retrying with "
                               f"OpenAI paid API ({PREFERRED_PAID_MODELS[0]})")
                stream = self.__get_response_stream(conversation=conversation, preferred_models=PREFERRED_PAID_MODELS,
                                           use_paid_api=True)
                # Move to a different model
            elif error_code == "RateLimitReached":
                # We have exhausted the free API limit for this model
                self.exhausted_models.append(model)
                print()
                logger.warning(f"Exhausted free API limit for model {model}. Retrying with a different model")
                if len(preferred_models) == 1 and not use_paid_api:
                    logger.warning("No more models to try. Retrying with the paid API")
                    stream = self.__get_response_stream(conversation=conversation, preferred_models=PREFERRED_PAID_MODELS,
                                             use_paid_api=True)
                else:
                    stream = self.__get_response_stream(conversation=conversation, preferred_models=preferred_models[1:],
                                                        use_paid_api=use_paid_api)
            elif error_code == 'unauthorized':
                raise PermissionError(f"Unauthorized: {error_message}")
            else:
                raise NotImplementedError(f"Error: {error_code} - {error_message}")


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
        # Remove trailing commas before closing brackets
        message = re.sub(r',\s*}', '}', message)
        try:
            return json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from message: {message}")
            raise json.JSONDecodeError


    def _replace_prompt_placeholders(self, prompt: str, cache: dict[str, str], accept_unfilled: bool = False) -> str:
        """
        Replace the placeholders in the prompt with the values in the cache
        :param prompt: The prompt to replace the placeholders
        :param cache: The cache with the values to replace
        :return: The prompt with the placeholders replaced
        """
        placeholders = re.findall(r'{(\w+)}', prompt)
        for placeholder in placeholders:
            if not accept_unfilled:
                assert placeholder in cache, f"Placeholder '{placeholder}' not found in the cache"
                prompt = prompt.replace(f'{{{placeholder}}}', str(cache[placeholder]))
            elif placeholder in cache:
                prompt = prompt.replace(f'{{{placeholder}}}', str(cache[placeholder]))
        return prompt

    def _generate_dict_from_prompts(self, prompts: list[dict], preferred_models: list = None,
                                    desc: str = "Generating", cache: dict = frozenset({})) -> dict:

        if preferred_models is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        cache = dict(deepcopy(cache))

        # Loop through each prompt and get a response
        for i, prompt_definition in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            assert all(key in prompt_definition for key in ('prompt', 'cache_key')), "Invalid prompt definition"
            prompt, cache_key = prompt_definition['prompt'], prompt_definition['cache_key']
            function_call = prompt_definition.get('function_call', None)
            system_prompt = prompt_definition.get('system_prompt', None)
            structured_json = prompt_definition.get('structured_json', None)
            if system_prompt is not None:
                system_prompt = self._replace_prompt_placeholders(prompt=system_prompt, cache=cache, accept_unfilled=function_call is not None)
            conversation = []
            if system_prompt is not None:
                conversation.append({'role': 'system', 'content': system_prompt})
            prompt = self._replace_prompt_placeholders(prompt=prompt, cache=cache, accept_unfilled=function_call is not None)
            conversation.append({'role': 'user', 'content': prompt})
            if function_call is not None:
                assert isinstance(function_call, str), "Invalid function call"
                assert hasattr(self, function_call), f"Function not found: {function_call}"
                # Get the function within this class
                function = getattr(self, function_call)
                # Call the function with the cache as the argument
                assistant_reply = function(cache=cache, system_prompt=system_prompt,
                                           prompt=prompt, preferred_models=preferred_models)
            else:
                # Get the assistant's response
                assistant_reply, finish_reason = self.get_model_response(conversation=conversation,
                                                                         preferred_models=preferred_models,
                                                                         structured_json=structured_json)
                if any(cant_assist.lower() in assistant_reply.lower() for cant_assist in CANNOT_ASSIST_PHRASES):
                    if len(preferred_models) == 0:
                        raise RuntimeError(f"No models can assist with prompt: {prompt}")
                    logger.warning(f"Assistant cannot assist with prompt: {prompt}. Retrying with a different model")
                    assistant_reply, finish_reason = self.get_model_response(conversation=conversation,
                                                                             preferred_models=preferred_models[1:])
            # Add the assistant's response to the cache
            cache[cache_key] = assistant_reply

        if isinstance(assistant_reply, dict):
            return assistant_reply

        assert isinstance(assistant_reply, str) and len(assistant_reply) > 0, "Assistant response not found"
        # Decode the JSON object for the last assistant_reply
        output_dict = self.decode_json_from_message(message=assistant_reply)
        return output_dict

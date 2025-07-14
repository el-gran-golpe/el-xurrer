from pathlib import Path
from dotenv import dotenv_values
import random
from copy import deepcopy
import json
import re
from typing import Iterable, Union, Optional, Literal, Any, cast

from azure.core.exceptions import HttpResponseError
from dotenv import load_dotenv
from openai import OpenAI, APIStatusError
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletion,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)
from pydantic import BaseModel, Field, ValidationError, model_validator, field_validator
from tqdm import tqdm
from loguru import logger

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    SystemMessage,
    UserMessage,
    StreamingChatCompletionsUpdate,
    AssistantMessage,
    ChatRequestMessage,
    ChatCompletions,
)
from azure.core.credentials import AzureKeyCredential

from llm.common.constants import (
    MODEL_BY_BACKEND,
    AZURE,
    OPENAI,
    PREFERRED_PAID_MODELS,
    DEFAULT_PREFERRED_MODELS,
    CANNOT_ASSIST_PHRASES,
    MODELS_NOT_ACCEPTING_SYSTEM_ROLE,
    MODELS_NOT_ACCEPTING_STREAM,
    VALIDATION_SYSTEM_PROMPT,
    MODELS_ACCEPTING_JSON_FORMAT,
    REASONING_MODELS,
    MODELS_INCLUDING_CHAIN_THOUGHT,
)

ENV_FILE = Path(__file__).parent / "api_key.env"


class ApiKey(BaseModel):
    api_key: str
    paid: bool = False


class LLMApiKeys(BaseModel):
    api_keys: dict[str, str] = Field(default_factory=dict)
    env_file: Path

    @model_validator(mode="before")
    @classmethod
    def load_all_api_keys(cls, values):
        env_file = values.get("env_file")
        if not env_file or not Path(env_file).is_file():
            raise FileNotFoundError(f"Missing API key file: {env_file}.")
        # Load all key-value pairs from the env file
        env_vars = dotenv_values(env_file)
        # Filter out empty values
        api_keys = {k: v for k, v in env_vars.items() if v}
        if not api_keys:
            raise ValueError("No API keys found in the env file.")
        values["api_keys"] = api_keys
        load_dotenv(env_file)
        return values

    @model_validator(mode="after")
    def at_least_one_key(self):
        if not self.api_keys:
            raise ValueError("At least one API key must be provided.")
        return self


class LLMConfig(BaseModel):
    preferred_models: list[str]

    @field_validator("preferred_models")
    @classmethod
    def not_empty(cls, v):
        if not v:
            raise ValueError("preferred_models must not be empty")
        return v


ResponseChunk = Union[
    (
        StreamingChatCompletionsUpdate,
        ChatCompletions,
        ChatCompletionChunk,
        ChatCompletion,
    )
]


class BaseLLM:
    def __init__(
        self, preferred_models: Union[list[str], str] = DEFAULT_PREFERRED_MODELS
    ):
        self.preferred_models = (
            [preferred_models]
            if isinstance(preferred_models, str)
            else preferred_models
        )
        self.preferred_validation_models: list[str] = DEFAULT_PREFERRED_MODELS[::-1]

        self.api_keys = self._load_api_keys()
        self.github_api_keys = self._extract_github_keys()
        self.openai_api_key = self._extract_openai_key()

        self.exhausted_models: list[str] = []
        self.client: Optional[Union[ChatCompletionsClient, OpenAI]] = None
        self.active_backend: Optional[Union[Literal["openai", "azure"]]] = None
        self.using_paid_api = False

    # --- Helper methods for API keys and clients ---
    def _load_api_keys(self) -> LLMApiKeys:
        try:
            return LLMApiKeys(env_file=ENV_FILE)
        except (ValidationError, FileNotFoundError) as e:
            raise ValueError(f"API key validation failed: {e}")

    def _extract_github_keys(self) -> list[ApiKey]:
        return [
            ApiKey(api_key=key, paid=False)
            for name, key in self.api_keys.api_keys.items()
            if "GITHUB" in name.upper()
        ]

    def _extract_openai_key(self) -> ApiKey:
        openai_keys = [
            key
            for name, key in self.api_keys.api_keys.items()
            if "OPENAI" in name.upper()
        ]
        if not openai_keys:
            raise ValueError("No OpenAI API key found in the env file.")
        return ApiKey(api_key=openai_keys[0], paid=True)

    # --- End of helper methods ---

    def get_client(self, model: str, paid_api: bool = False):
        assert model in MODEL_BY_BACKEND, f"Model not found: {model}"
        backend = MODEL_BY_BACKEND[model]
        if paid_api:
            assert backend == OPENAI, "Paid API is only available for OpenAI models"

        if (
            self.active_backend == backend
            and self.client is not None
            and self.using_paid_api == paid_api
        ):
            return self.client

        if backend == OPENAI:
            return self.get_new_client_openai(paid_api=paid_api)
        elif backend == AZURE:
            return self.get_new_client_azure()
        else:
            raise NotImplementedError(f"Backend not implemented: {backend}")

    def get_new_client_azure(self):
        assert len(self.github_api_keys) > 0, (
            "Missing GITHUB_API_KEY for Azure authentication"
        )
        github_api_key = random.choice(self.github_api_keys)
        if github_api_key:
            self.client = ChatCompletionsClient(
                endpoint="https://models.inference.ai.azure.com",
                credential=AzureKeyCredential(github_api_key),
            )
        self.active_backend = AZURE
        self.using_paid_api = False
        return self.client

    def get_new_client_openai(self, paid_api: bool = False):
        # First of all, try to use the GitHub API key if available (Is free)
        # We are routing to azure first because it's free using our GitHub api keys and also because azure api is
        # compatible with OpenAI's API
        if not paid_api:
            api_key: ApiKey = random.choice(self.github_api_keys)
            base_url = "https://models.inference.ai.azure.com"
        else:
            api_key = self.openai_api_key
            base_url = None

        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key.api_key,
        )

        self.active_backend = OPENAI
        self.using_paid_api = paid_api
        return self.client

    def get_model_response(
        self,
        conversation: list[dict],
        preferred_models: list[str] = [],
        preferred_validation_models: list[str] = [],
        verbose: bool = True,
        structured_json: Optional[dict[str, Union[str, dict[str, Any]]]] = None,
        as_json: bool = False,
        large_output: bool = False,
        validate: bool = False,
        force_reasoning: bool = False,
    ) -> tuple:
        if len(preferred_models) == 0:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        stream = self.__get_response_stream(
            conversation=conversation,
            preferred_models=preferred_models,
            structured_json=structured_json,
            as_json=as_json,
            large_output=large_output,
            force_reasoning=force_reasoning,
        )

        assistant_reply, finish_reason = "", None
        for chunk in stream:
            if len(chunk.choices) == 0:
                continue
            current_finish_reason = chunk.choices[0].finish_reason
            # delta will be available when streaming the response. Otherwise, the info will just come at message
            new_content = (
                chunk.choices[0].delta.content
                if hasattr(chunk.choices[0], "delta")
                else chunk.choices[0].message.content
            )

            if new_content is not None:
                assistant_reply += new_content
                if verbose:
                    print(new_content, end="")

            if current_finish_reason is not None:
                finish_reason = current_finish_reason

        # TODO: That's for non-gpt models that seems to not return a finish reason
        model = [
            model for model in preferred_models if model not in self.exhausted_models
        ][0]
        if (
            not (model.startswith("gpt-") or model.startswith("o1"))
            and finish_reason is None
        ):
            logger.debug(f"Model {model} did not return a finish reason. Assuming stop")
            finish_reason = "stop"

        if model in MODELS_INCLUDING_CHAIN_THOUGHT:
            # Remove <think> ... </think> tags from the assistant reply
            assistant_reply = re.sub(
                pattern=r"<think>.*?</think>",
                repl="",
                string=assistant_reply,
                flags=re.DOTALL,
            ).strip()

        if finish_reason == "stop" and validate:
            finish_reason, assistant_reply = self.recalculate_finish_reason(
                assistant_reply=assistant_reply
            )
        assert finish_reason is not None, (
            "Finish reason not found"
        )  # FIXME: This is a problem for unattended running

        if finish_reason == "length":
            continue_conversation = deepcopy(conversation)
            continue_conversation.append(
                {"role": "assistant", "content": assistant_reply}
            )
            continue_conversation.append(
                {"role": "user", "content": "Continue EXACTLY where we left off"}
            )
            new_assistant_reply, finish_reason = self.get_model_response(
                conversation=continue_conversation,
                preferred_models=preferred_models,
                as_json=as_json,
                large_output=large_output,
                validate=validate,
            )
            assistant_reply += new_assistant_reply

        elif finish_reason == "content_filter":
            print("\n")
            logger.debug("Content filter triggered. Retrying with a different model")
            assert len(preferred_models) > 1, "No more models to try"
            assistant_reply, finish_reason = self.get_model_response(
                conversation=conversation,
                preferred_models=preferred_models[1:],
                as_json=as_json,
                large_output=large_output,
                validate=validate,
            )

        assert finish_reason == "stop", f"Unexpected finish reason: {finish_reason}"
        return assistant_reply, finish_reason

    def __get_response_stream(
        self,
        conversation: list[dict],
        preferred_models: list[str],
        use_paid_api: bool = False,
        structured_json: dict[str, str | dict]
        | None = None,  # TODO:  remove unused code
        as_json: bool = False,
        large_output: bool = False,
        force_reasoning: bool = False,
        stream_response: bool = True,
    ) -> Iterable[ResponseChunk]:
        conversation = deepcopy(conversation)
        additional_params: dict[str, Any] = {}

        # --------------------------------------------------------------------
        # Select the best model that is not exhausted
        if not use_paid_api:
            preferred_models = [
                model
                for model in preferred_models
                if model not in self.exhausted_models
            ]

        if as_json:
            preferred_models = [
                model
                for model in preferred_models
                if model in MODELS_ACCEPTING_JSON_FORMAT
            ]
            additional_params["response_format"] = {"type": "json_object"}
            # FIXME: This can be done in a way more explicit, for example using a flag and it has to be specific for
            #  OpenAI and Azure because the API is different

        if force_reasoning:
            # Use the order of REASONING_MODELS to be better first
            reasoning_models = [
                model for model in REASONING_MODELS if model in preferred_models
            ]
            if len(reasoning_models) > 0:
                preferred_models = reasoning_models
            else:
                logger.warning(
                    f"Couldn't force a reasoning models because no one available. Using {preferred_models[0]}"
                )

        assert len(preferred_models) > 0, "No models available"
        model: str = preferred_models[0]
        logger.info(f"Using model: {model}")

        if model in MODELS_NOT_ACCEPTING_SYSTEM_ROLE:
            conversation = self.merge_system_and_user_messages(
                conversation=conversation
            )

        self.client = self.get_client(model=model, paid_api=use_paid_api)
        stream_response = stream_response and model not in MODELS_NOT_ACCEPTING_STREAM
        raw_response: Union[Iterable[ResponseChunk], ResponseChunk]

        try:
            if self.active_backend == AZURE:
                if not isinstance(self.client, ChatCompletionsClient):
                    raise ValueError(f"Client is not Azure: {self.client} - {model}")
                raw_response = self.client.complete(
                    messages=self.conversation_to_azure_format(
                        conversation=conversation
                    ),
                    model=model,
                    stream=stream_response,
                    **additional_params,
                )
            elif self.active_backend == OPENAI:
                if not isinstance(self.client, OpenAI):
                    raise ValueError(f"Client is not OpenAI: {self.client} - {model}")
                raw_response = self.client.chat.completions.create(
                    messages=self.conversation_to_openai_format(
                        conversation=conversation
                    ),
                    model=model,
                    stream=stream_response,
                    **additional_params,
                )
            else:
                raise NotImplementedError(
                    f"Backend not implemented: {self.active_backend}"
                )

            if not stream_response and not isinstance(raw_response, Iterable):
                stream: Iterable[ResponseChunk] = [raw_response]
            else:
                stream = cast(Iterable[ResponseChunk], raw_response)

        except (APIStatusError, HttpResponseError) as e:
            if isinstance(e, APIStatusError):
                error_code = e.code
                error_message = e.message
            elif isinstance(e, HttpResponseError):
                error_code = (
                    e.error.code
                    if e.error is not None and e.error.code is not None
                    else str(e)
                )
                error_message = (
                    e.error.message
                    if e.error is not None and e.error.message is not None
                    else str(e)
                )
            else:
                raise e

            if error_code == "tokens_limit_reached":
                # Context token limit reached. So we'll have to move to the OpenAI paid API for this
                assert not use_paid_api, (
                    "This error should not happen when using the paid API"
                )
                print()
                logger.warning(
                    f"Request size exceeded free github API limit. Retrying with "
                    f"OpenAI paid API ({PREFERRED_PAID_MODELS[0]})"
                )
                stream = self.__get_response_stream(
                    conversation=conversation,
                    preferred_models=PREFERRED_PAID_MODELS,
                    use_paid_api=True,
                    as_json=as_json,
                    force_reasoning=False,
                )
                # Move to a different model
            elif error_code == "RateLimitReached":
                # We have exhausted the free API limit for this model
                self.exhausted_models.append(model)
                print()
                logger.warning(
                    f"Exhausted free API limit for model {model}. Retrying with a different model"
                )
                if len(preferred_models) == 1 and not use_paid_api:
                    logger.warning("No more models to try. Retrying with the paid API")
                    stream = self.__get_response_stream(
                        conversation=conversation,
                        preferred_models=PREFERRED_PAID_MODELS,
                        use_paid_api=True,
                        as_json=as_json,
                        force_reasoning=False,
                    )
                else:
                    stream = self.__get_response_stream(
                        conversation=conversation,
                        preferred_models=preferred_models[1:],
                        use_paid_api=use_paid_api,
                        as_json=as_json,
                        large_output=large_output,
                        force_reasoning=force_reasoning,
                    )
            elif error_code == "content_filter":
                logger.warning(
                    f"Content filter triggered for model {model}. Retrying with a different model"
                )
                assert len(preferred_models) > 1, "No more models to try"
                stream = self.__get_response_stream(
                    conversation=conversation,
                    preferred_models=preferred_models[1:],
                    use_paid_api=use_paid_api,
                    as_json=as_json,
                    large_output=large_output,
                    force_reasoning=force_reasoning,
                )
            elif error_code == "unauthorized":
                raise PermissionError(f"Unauthorized: {error_message}")
            else:
                raise NotImplementedError(f"Error: {error_code} - {error_message}")

        return stream

    def conversation_to_azure_format(
        self, conversation: list[dict]
    ) -> list[ChatRequestMessage]:
        azure_conversation = []
        for message in conversation:
            assert "content" in message and "role" in message, (
                f"Invalid message format: {message}"
            )
            content, role = message["content"], message["role"]
            if role == "user":
                azure_message: ChatRequestMessage = UserMessage(content=content)
            elif role == "assistant":
                azure_message = AssistantMessage(content=content)
            elif role == "system":
                azure_message = SystemMessage(content=content)
            else:
                raise ValueError(f"Invalid role: {role}")
            azure_conversation.append(azure_message)
        return azure_conversation

    def decode_json_from_message(self, message: str) -> dict:
        if message.startswith("```json"):
            message = message[len("```json") : -len("```")]

            # THOUGHTS: Check why is this used three times, I think is because of the json format but check it anyway
            message = (
                message.replace("\n```json", "")
                .replace("```json\n", "")
                .replace("```json", "")
            )

        message = message.strip('"')
        # Remove trailing commas before closing brackets
        message = re.sub(r",\s*}", "}", message)
        try:
            return json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from message: {message}")
            raise

    def merge_system_and_user_messages(self, conversation: list[dict]) -> list[dict]:
        """
        for each message, if its 'role' is 'system', merge it with the next 'user' message
        :param conversation: The conversation to merge. A list of dictionaries with 'role' and 'content'
        :return: The conversation with the system messages merged with the next user message
        """
        # TODO: why is this a for loop? This is called for a conversation that seems to be composed of system_prompt
        #  and prompt
        merged_conversation, last_system_message = [], None
        for i, message in enumerate(conversation):
            role, content = message["role"], message["content"]
            # If is a system message, keep it in memory to merge it with the next user message
            if role == "system":
                assert i < len(conversation) - 1, (
                    f"System message is the last message while merging.\n\n {conversation}"
                )
                assert last_system_message is None, (
                    "Two consecutive system messages found"
                )
                last_system_message = content
            # If is a user message, merge it with the previous system message as user message
            elif role == "user":
                # If there was a system message before, merge it with the user message
                if last_system_message is not None:
                    new_message = last_system_message + "\n\n" + content
                    merged_conversation.append({"role": "user", "content": new_message})
                    last_system_message = None
                # Otherwise, just append the user message
                else:
                    merged_conversation.append(message)
            # If not a system or user message, just append
            else:
                # First make sure that it is an assistant message
                assert role in ("assistant",), f"Unexpected role: {role}"
                merged_conversation.append(message)

        assert last_system_message is None, (
            "Last message was a system message. Unexpected"
        )

        return merged_conversation

    def _replace_prompt_placeholders(
        self, prompt: str, cache: dict[str, str], accept_unfilled: bool = False
    ) -> str:
        """
        Replace the placeholders in the prompt_spec? with the values in the cache
        :param prompt: The prompt to replace the placeholders
        :param cache: The cache with the values to replace
        :return: The prompt with the placeholders replaced
        """
        placeholders = re.findall(r"{(\w+)}", prompt)
        for placeholder in placeholders:
            if not accept_unfilled:
                assert placeholder in cache, (
                    f"Placeholder '{placeholder}' not found in the cache"
                )
                prompt = prompt.replace(f"{{{placeholder}}}", str(cache[placeholder]))
            elif placeholder in cache:
                prompt = prompt.replace(f"{{{placeholder}}}", str(cache[placeholder]))
        return prompt

    def _generate_dict_from_prompts(
        self,
        prompts: list[dict],
        desc: str = "Generating",
        cache: dict[str, str] = dict(),
    ) -> dict:
        preferred_models = self.preferred_models

        # Loop through each prompt_spec (that is, a ternary of system_promt + prompt + cache_key specified in
        # the .json) and get a response
        for i, prompt_spec in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            # These 3 variables can never be empty according to profile.py
            system_prompt, prompt, cache_key = (
                prompt_spec["system_prompt"],
                prompt_spec["prompt"],
                prompt_spec["cache_key"],
            )
            # These other variables are optional
            function_call = prompt_spec.get("function_call", None)  # FIXME: ask Haru
            structured_json = prompt_spec.get("structured_json", None)
            as_json = prompt_spec.get("json", False)
            force_reasoning = prompt_spec.get("force_reasoning", False)
            large_output = prompt_spec.get("large_output", False)
            validate = prompt_spec.get("validate", False)

            # --- Prepare the conversation ---
            conversation = [
                {
                    "role": "system",
                    "content": self._replace_prompt_placeholders(
                        prompt=system_prompt,
                        cache=cache,
                        accept_unfilled=function_call is not None,
                    ),
                },
                {
                    "role": "user",
                    "content": self._replace_prompt_placeholders(
                        prompt=prompt,
                        cache=cache,
                        accept_unfilled=function_call is not None,
                    ),
                },
            ]

            if function_call is not None:
                assert isinstance(function_call, str), "Invalid function call"
                assert hasattr(self, function_call), (
                    f"Function not found: {function_call}"
                )
                # Get the function within this class
                function = getattr(self, function_call)
                # Call the function with the cache as the argument
                assistant_reply = function(
                    cache=cache,
                    system_prompt=system_prompt,
                    prompt=prompt,
                    preferred_models=preferred_models,
                )
            else:
                # Get the assistant's response
                assistant_reply, finish_reason = self.get_model_response(
                    conversation=conversation,
                    preferred_models=preferred_models,
                    structured_json=structured_json,
                    as_json=as_json,
                    large_output=large_output,
                    validate=validate,
                    force_reasoning=force_reasoning,
                )

                if any(
                    cant_assist.lower() in assistant_reply.lower()
                    for cant_assist in CANNOT_ASSIST_PHRASES
                ):
                    if len(preferred_models) == 0:
                        raise RuntimeError(
                            f"No models can assist with prompt: {prompt}"
                        )
                    logger.warning(
                        f"Assistant cannot assist with prompt: {prompt}. Retrying with a different model"
                    )
                    assistant_reply, finish_reason = self.get_model_response(
                        conversation=conversation,
                        preferred_models=preferred_models[1:],
                        as_json=as_json,
                        large_output=large_output,
                        validate=validate,
                        force_reasoning=force_reasoning,
                    )
            # Add the assistant's response to the cache
            cache[cache_key] = assistant_reply

        if isinstance(assistant_reply, dict):
            return assistant_reply

        assert isinstance(assistant_reply, str) and len(assistant_reply) > 0, (
            "Assistant response not found"
        )
        # Decode the JSON object for the last assistant_reply
        output_dict = self.decode_json_from_message(message=assistant_reply)
        return output_dict

    def recalculate_finish_reason(self, assistant_reply: str) -> tuple[str, str]:
        """
        Validate that the finish reason is the expected one
        :param finish_reason: The finish reason to validate
        :param expected_finish_reason: The expected finish reason
        :return: True if the finish reason is the expected one
        """

        conversation = [
            {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
            {"role": "user", "content": assistant_reply},
        ]

        print("\n\n----------------- VALIDATION -----------------")
        output_dict, finish_reason = self.get_model_response(
            conversation=conversation,
            preferred_models=self.preferred_validation_models,
            as_json=True,
            validate=False,
            large_output=False,
            force_reasoning=False,
        )
        print()
        # Decode the JSON object for the last assistant_reply
        output_dict = self.decode_json_from_message(message=output_dict)

        assert "finish_reason" in output_dict, (
            f"Finish reason not found in the output: {output_dict}"
        )
        assert "markers" in output_dict, (
            f"Markers not found in the output: {output_dict}"
        )

        finish_reason, markers = output_dict["finish_reason"], output_dict["markers"]
        if finish_reason == "stop":
            assert len(markers) == 0, (
                f"Markers found in the assistant reply when finish_reason is stop: "
                f"{markers}"
            )
        for marker in markers:
            # Sometimes the final dots are a problem. So remove them if it's the case
            marker = f"{marker}."
            while marker not in assistant_reply and marker.endswith("."):
                marker = marker[:-1]
            assert marker in assistant_reply, (
                f"Marker not found in the assistant reply: {marker}"
            )

            assistant_reply = assistant_reply.replace(marker, "").strip()
        if assistant_reply == "":
            logger.error("Assistant reply is empty after removing the markers")
            finish_reason = "stop"
        return finish_reason, assistant_reply

    def conversation_to_openai_format(
        self, conversation: list[dict]
    ) -> list[
        Union[
            ChatCompletionSystemMessageParam,
            ChatCompletionUserMessageParam,
            ChatCompletionAssistantMessageParam,
        ]
    ]:
        openai_conversation = []
        for message in conversation:
            assert "content" in message and "role" in message, (
                f"Invalid message format: {message}"
            )
            content, role = message["content"], message["role"]
            if role == "user":
                openai_message: Union[
                    ChatCompletionUserMessageParam,
                    ChatCompletionSystemMessageParam,
                    ChatCompletionAssistantMessageParam,
                ] = ChatCompletionUserMessageParam(content=content, role=role)
            elif role == "assistant":
                openai_message = ChatCompletionAssistantMessageParam(
                    content=content, role=role
                )
            elif role == "system":
                openai_message = ChatCompletionSystemMessageParam(
                    content=content, role=role
                )
            else:
                raise ValueError(f"Invalid role: {role}")
            openai_conversation.append(openai_message)
        return openai_conversation

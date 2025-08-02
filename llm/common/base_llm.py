from copy import deepcopy
import re
from typing import Iterable, Union, Optional, Literal, Any, cast
from llm.common.conversation_format import (
    conversation_to_openai_format,
    conversation_to_azure_format,
)

from azure.core.exceptions import HttpResponseError
from openai import OpenAI, APIStatusError
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletion,
)
from pydantic import BaseModel, field_validator
from tqdm import tqdm
from loguru import logger

from llm.common.api_keys import api_keys

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    StreamingChatCompletionsUpdate,
    ChatCompletions,
)

from llm.common.clients import LLMClientManager
from llm.common.constants import (
    AZURE,
    OPENAI,
    PREFERRED_PAID_MODELS,
    DEFAULT_PREFERRED_MODELS,
    CANNOT_ASSIST_PHRASES,
    MODELS_NOT_ACCEPTING_SYSTEM_ROLE,
    MODELS_NOT_ACCEPTING_STREAM,
    MODELS_ACCEPTING_JSON_FORMAT,
    REASONING_MODELS,
    MODELS_INCLUDING_CHAIN_THOUGHT,
)

from llm.common.constants import MODEL_BY_BACKEND
from llm.common.prompt_utils import replace_prompt_placeholders
from llm.common.conversation_format import (
    merge_system_and_user_messages,
)
from llm.common.response import decode_json_from_message
from llm.common.response import recalculate_finish_reason
# Maybe the above file should be renamed to validation.py or something similar


class LLMConfig(BaseModel):
    preferred_models: list[str]

    @field_validator("preferred_models")
    @classmethod
    def not_empty(cls, v):
        if not v:
            raise ValueError("preferred_models must not be empty")
        return v


class PromptSpecification(BaseModel):
    system_prompt: str
    prompt: str
    cache_key: str


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
        # TODO: think how to pick up the api keys in case there are 2 or more
        self.github_api_keys: list[str] = api_keys.extract_github_keys()
        self.openai_api_keys: list[str] = api_keys.extract_openai_keys()

        self.client_manager = LLMClientManager(
            github_api_keys=self.github_api_keys,
            openai_api_keys=self.openai_api_keys,
        )

        # Use Pydantic LLMConfig for validation
        config = LLMConfig(
            preferred_models=[preferred_models]
            if isinstance(preferred_models, str)
            else preferred_models
        )

        self.preferred_models = config.preferred_models
        self.preferred_validation_models: list[str] = DEFAULT_PREFERRED_MODELS[::-1]

        self.exhausted_models: list[str] = []
        self.client: Optional[Union[ChatCompletionsClient, OpenAI]] = None
        self.active_backend: Optional[Union[Literal["openai", "azure"]]] = None
        self.using_paid_api = False

    # --- Methods for generating responses from prompts ---
    # TODO: pass the actual prompt_spec instead of a dict
    def _generate_dict_from_prompts(
        self,
        prompts: list[PromptSpecification],
        tqdm_description: str = "Generating",
        cache: dict[str, str] = dict(),  # TODO: understand this cache better
    ) -> dict:
        preferred_models = self.preferred_models

        # Loop through each prompt_spec (that is, a ternary of system_promt + prompt + cache_key specified in
        # the .json) and get a response
        for i, prompt_spec in tqdm(
            enumerate(prompts), desc=tqdm_description, total=len(prompts)
        ):
            # These other variables are optional
            # function_call = prompt_spec.get("function_call", None)  # FIXME: ask Haru
            # structured_json = prompt_spec.get("structured_json", None)
            as_json = prompt_spec.get("json", False)
            force_reasoning = prompt_spec.get("force_reasoning", False)
            large_output = prompt_spec.get("large_output", False)
            validate = prompt_spec.get("validate", False)

            # --- Replace {placeholders} for their cache value ---
            conversation = [
                {
                    "role": "system",
                    "content": replace_prompt_placeholders(
                        prompt=prompt_spec["system_prompt"],
                        cache=cache,
                        # accept_unfilled=function_call is not None,
                        accept_unfilled=False,
                    ),
                },
                {
                    "role": "user",
                    "content": replace_prompt_placeholders(
                        prompt=prompt_spec["prompt"],
                        cache=cache,
                        # accept_unfilled=function_call is not None,
                        accept_unfilled=False,
                    ),
                },
            ]

            # TODO: what the hell is this function_call? --> No clue, I will remove it for now since it is not used
            # if function_call is not None:
            #     assert isinstance(function_call, str), "Invalid function call"
            #     assert hasattr(self, function_call), (
            #         f"Function not found: {function_call}"
            #     )
            #     # Get the function within this class
            #     function = getattr(self, function_call)
            #     # Call the function with the cache as the argument
            #     assistant_reply = function(
            #         cache=cache,
            #         system_prompt=system_prompt,
            #         prompt=prompt,
            #         preferred_models=preferred_models,
            #     )
            # else:
            # Get the assistant's response
            assistant_reply, finish_reason = self._get_model_response(
                conversation=conversation,
                preferred_models=preferred_models,
                # structured_json=structured_json,
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
                        f"No models can assist with prompt: {prompt_spec['prompt']}"
                    )
                logger.warning(
                    f"Assistant cannot assist with prompt: {prompt_spec['prompt']}. Retrying with a different model"
                )
                # TODO: it does not make sense to retry with a different model if the
                # _get_model_response does not accept a preferred_models argument
                assistant_reply, finish_reason = self._get_model_response(
                    conversation=conversation,
                    preferred_models=preferred_models[1:],
                    as_json=as_json,
                    large_output=large_output,
                    validate=validate,
                    force_reasoning=force_reasoning,
                )
            # Add the assistant's response to the cache
            cache[prompt_spec["cache_key"]] = assistant_reply

        if isinstance(assistant_reply, dict):
            return assistant_reply

        assert isinstance(assistant_reply, str) and len(assistant_reply) > 0, (
            "Assistant response not found"
        )
        # Decode the JSON object for the last assistant_reply
        output_dict = decode_json_from_message(message=assistant_reply)
        return output_dict

    def _get_model_response(
        self,
        conversation: list[dict],
        verbose: bool = True,
        as_json: bool = False,
        large_output: bool = False,
        validate: bool = False,
        force_reasoning: bool = False,
        preferred_models: Optional[list[str]] = None,
    ) -> tuple:
        preferred_models = self.preferred_models

        stream = self.__get_response_stream(
            conversation=conversation,
            preferred_models=preferred_models,
            as_json=as_json,
            large_output=large_output,
            force_reasoning=force_reasoning,
        )

        # --- Stream the response and collect the assistant reply ---
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
        # --- End of streaming the response ---

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
            finish_reason, assistant_reply = recalculate_finish_reason(
                assistant_reply=assistant_reply,
                get_model_response=self._get_model_response,
                preferred_validation_models=self.preferred_validation_models,
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
            new_assistant_reply, finish_reason = self._get_model_response(
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
            assistant_reply, finish_reason = self._get_model_response(
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
        as_json: bool = False,
        large_output: bool = False,
        force_reasoning: bool = False,
        stream_response: bool = True,
    ) -> Iterable[ResponseChunk]:
        conversation = deepcopy(conversation)
        additional_params: dict[str, Any] = {}

        # Select the best model that is not exhausted
        # TODO: (MOI) this is not the best way to do it, this could be a funcioncita to pick up desired model
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

        assert len(preferred_models) > 0, (
            "No models available"
        )  # TODO: (MOI) this should be a warning and we need to default to some model because we don't want to fail the pipeline
        model: str = preferred_models[0]
        logger.info(f"Using model: {model}")

        if model in MODELS_NOT_ACCEPTING_SYSTEM_ROLE:
            conversation = merge_system_and_user_messages(conversation=conversation)

        self.client = self.client_manager.get_client(
            model=model,
            free_api=not use_paid_api,
            MODEL_BY_BACKEND=MODEL_BY_BACKEND,
            OPENAI=OPENAI,
            AZURE=AZURE,
        )
        self.active_backend = self.client_manager.active_backend
        self.using_paid_api = self.client_manager.using_paid_api

        stream_response = stream_response and model not in MODELS_NOT_ACCEPTING_STREAM
        raw_response: Union[Iterable[ResponseChunk], ResponseChunk]

        try:
            # TODO: here its calling the api, update it with the new client
            # TODO: (MOI) make a method to call the llm without knowing wich backend is using
            if self.active_backend == AZURE:
                raw_response = self.call_azure(
                    additional_params,
                    conversation,
                    model,
                    stream_response,
                )
            elif self.active_backend == OPENAI:
                if not isinstance(self.client, OpenAI):
                    raise ValueError(f"Client is not OpenAI: {self.client} - {model}")
                raw_response = self.client.chat.completions.create(
                    messages=conversation_to_openai_format(conversation=conversation),
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

    def call_azure(self, additional_params, conversation, model, stream_response):
        if not isinstance(self.client, ChatCompletionsClient):
            raise ValueError(f"Client is not Azure: {self.client} - {model}")
        raw_response = self.client.complete(
            messages=conversation_to_azure_format(conversation=conversation),
            model=model,
            stream=stream_response,
            **additional_params,
        )
        return raw_response

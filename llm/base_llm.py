import json
from pathlib import Path
import re
from copy import deepcopy
from typing import Iterable, Union, Optional, Literal, Any

from loguru import logger
from pydantic import BaseModel, field_validator, ConfigDict
from tqdm import tqdm

from llm.common.api_keys import api_keys
from llm.common.backend_invoker import invoke_backend
from llm.common.clients import LLMClientManager
from llm.common.routing.content_classifier import ContentClassifier
from llm.constants import (
    DEFAULT_PREFERRED_MODELS,
    CANNOT_ASSIST_PHRASES,
    MODELS_INCLUDING_CHAIN_THOUGHT,
    MODEL_BY_BACKEND,
)
from llm.common.conversation_builder import prepare_conversation
from llm.common.error_handler import handle_api_error
from llm.common.model_selector import select_models
from llm.common.request_options import RequestOptions
from llm.common.response import decode_json_from_message, recalculate_finish_reason
from llm.utils import get_closest_monday
from main_components.common.constants import Platform
from llm.types import PromptSpecification
from llm.common.routing.model_router import ModelRouter

ResponseChunk = Any  # upstream unioned types are defined in backend_invoker


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_models: list[str]

    @field_validator("preferred_models")
    @classmethod
    def not_empty(cls, v):
        if not v:
            raise ValueError("preferred_models must not be empty")
        return v


class BaseLLM:
    def __init__(
        self,
        prompt_json_template_path: Path,
        previous_storyline: str,
        platform_name: Platform,
        preferred_models: Union[list[str], str] = DEFAULT_PREFERRED_MODELS,
    ):
        # Github models and OpenAI API keys
        self.github_api_keys: list[str] = api_keys.extract_github_keys()
        self.openai_api_keys: list[str] = api_keys.extract_openai_keys()
        self.client_manager = LLMClientManager(
            github_api_keys=self.github_api_keys, openai_api_keys=self.openai_api_keys
        )

        config = LLMConfig(
            preferred_models=[preferred_models]
            if isinstance(preferred_models, str)
            else preferred_models
        )
        self.preferred_models = config.preferred_models
        self.preferred_validation_models: list[str] = DEFAULT_PREFERRED_MODELS[::-1]

        self.exhausted_models: list[str] = []
        self.active_backend: Optional[Literal["openai", "azure"]] = None
        self.using_paid_api = False

        # The new stuff that I am including
        self.prompt_json_template_path = prompt_json_template_path
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name

    # --- Helper methods ---
    def _load_and_prepare_prompts(self) -> list[PromptSpecification]:
        with self.prompt_json_template_path.open("r", encoding="utf-8") as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        lang = prompt_template.get(
            "lang", "en"
        )  # TODO: are we going to support other languages?
        monday_date = get_closest_monday().strftime("%Y-%m-%d")
        monday = "Monday" if lang == "en" else "Lunes"
        day = f"{monday} {monday_date}"

        if prompts and self.previous_storyline:
            prompts[0]["prompt"] = prompts[0]["prompt"].format(
                previous_storyline=self.previous_storyline
            )
        for prompt in prompts:
            if "system_prompt" in prompt:
                prompt["system_prompt"] = prompt["system_prompt"].format(day=day)

        # TODO: Maybe pydantic is redundant here, since this is checked in profile.py
        return [PromptSpecification.model_validate(prompt) for prompt in prompts]

    def _clean_chain_of_thought(self, model: str, assistant_reply: str) -> str:
        if model in MODELS_INCLUDING_CHAIN_THOUGHT:
            return re.sub(
                r"<think>.*?</think>", "", assistant_reply, flags=re.DOTALL
            ).strip()
        return assistant_reply

    # --- End of helper methods ---

    def generate_dict_from_prompts(self) -> dict:
        prompt_specs: list[PromptSpecification] = self._load_and_prepare_prompts()

        # TODO: maybe this contentclassifier can be included inside ModelRouter?
        content_classifier = ContentClassifier()
        content_type: Literal["hot", "innocent"] = content_classifier.classify_prompts(
            prompt_specs
        )

        # Might be interesting to use the prompt_specs because I only need
        # the json outputting in the last conversation/prompt
        # Maybe I can play with this
        model_router = ModelRouter(pat_keys=self.github_api_keys)
        # TODO: this has to be alive -> put it in __init__?
        # TODO: Assume model router is implemented and see where do I need it in the base llm (smart)
        model_router.get_models(content_type=content_type, prompt_spec=prompt_specs[0])

        # 3rd step is to use the ModelRouting Policy to pick up the best model for the prompt
        models_override = (
            list(self.preferred_models)
            if self.preferred_models is not None
            else list(self.preferred_models)
        )

        last_reply: Union[str, dict] = ""

        prompts = self._load_and_prepare_prompts() if not prompt_specs else prompt_specs

        # For each model in the ordered list: then we do this
        for raw_spec in tqdm(
            prompts, desc="Generating text with AI", total=len(prompts)
        ):
            # Normalize into dict via PromptSpecification if needed
            if isinstance(raw_spec, dict):
                spec = PromptSpecification.model_validate(raw_spec)
            elif isinstance(raw_spec, PromptSpecification):
                spec = raw_spec
            else:
                # attempt attribute access
                spec = PromptSpecification.model_validate(raw_spec.__dict__)  # type: ignore
            cache: dict = {}
            conversation = prepare_conversation(
                spec=spec.model_dump(), cache=cache
            )  # TODO: careful here
            options = RequestOptions(
                as_json=spec.json,
                large_output=spec.large_output,
                validate=spec.validate,
                force_reasoning=spec.force_reasoning,
            )

            assistant_reply, finish_reason = self._get_model_response(
                conversation=conversation,
                options=options,
                preferred_models=models_override,
                verbose=True,
            )

            if any(
                cant_assist.lower() in assistant_reply.lower()
                for cant_assist in CANNOT_ASSIST_PHRASES
            ):
                if len(models_override) <= 1:
                    raise RuntimeError(
                        f"No models can assist with prompt: {spec.prompt}"
                    )
                logger.warning(
                    "Assistant cannot assist with prompt: {}. Retrying with next model(s): {}",
                    spec.prompt,
                    models_override[1:],
                )
                models_override = models_override[1:]
                assistant_reply, finish_reason = self._get_model_response(
                    conversation=conversation,
                    options=options,
                    preferred_models=models_override,
                    verbose=True,
                )

            cache[spec.cache_key] = assistant_reply
            last_reply = assistant_reply

        if isinstance(last_reply, dict):
            return last_reply  # type: ignore
        output = decode_json_from_message(message=last_reply)
        return output

    def _get_model_response(
        self,
        conversation: list[dict],
        options: Optional[RequestOptions] = None,
        verbose: bool = True,
        preferred_models: Optional[list[str]] = None,
    ) -> tuple[str, str]:
        if options is None:
            options = RequestOptions()
        models = (
            list(preferred_models)
            if preferred_models is not None
            else list(self.preferred_models)
        )
        assistant_reply = ""
        finish_reason: Optional[str] = None
        convo = conversation

        while models:
            selected_models = select_models(
                base_models=models,
                exhausted_models=self.exhausted_models,
                options=options,
                use_paid_api=False,
            )
            model = selected_models[0]
            logger.info("Using model: {}", model)

            additional_params: dict[str, Any] = {}
            if options.as_json:
                additional_params["response_format"] = {"type": "json_object"}

            try:
                stream = self.__get_response_stream(
                    conversation=convo,
                    preferred_models=selected_models,
                    use_paid_api=False,
                    options=options,
                    stream_response=True,
                )
            except Exception as e:
                stream = handle_api_error(
                    e=e,
                    conversation=convo,
                    preferred_models=selected_models,
                    exhausted_models=self.exhausted_models,
                    use_paid_api=False,
                    options=options,
                    stream_response=True,
                    get_stream_callable=self.__get_response_stream,
                )

            assistant_reply = ""
            finish_reason = None

            for chunk in stream:
                if not hasattr(chunk, "choices") or len(chunk.choices) == 0:
                    continue
                choice = chunk.choices[0]
                current_finish_reason = getattr(choice, "finish_reason", None)
                if hasattr(choice, "delta"):
                    new_content = getattr(choice.delta, "content", None)
                else:
                    new_content = getattr(choice.message, "content", None)

                if new_content:
                    assistant_reply += new_content
                    if verbose:
                        logger.info("{}", new_content)

                if current_finish_reason is not None:
                    finish_reason = current_finish_reason

            non_exhausted = [
                m for m in selected_models if m not in self.exhausted_models
            ]
            used_model = non_exhausted[0] if non_exhausted else selected_models[0]

            if (
                not (used_model.startswith("gpt-") or used_model.startswith("o1"))
                and finish_reason is None
            ):
                logger.debug(
                    "Model {} did not return finish reason. Assuming stop", used_model
                )
                finish_reason = "stop"

            assistant_reply = self._clean_chain_of_thought(
                model=used_model, assistant_reply=assistant_reply
            )

            if finish_reason == "stop" and options.validate:
                try:
                    finish_reason, assistant_reply = recalculate_finish_reason(
                        assistant_reply=assistant_reply,
                        get_model_response_callable=lambda **k: self._get_model_response(
                            **k
                        ),
                        preferred_validation_models=self.preferred_validation_models,
                    )
                except Exception:
                    logger.warning(
                        "Validation finish_reason failed; proceeding with current reply"
                    )

            if finish_reason is None:
                raise RuntimeError("Finish reason not found for model response")

            if any(
                cant_assist.lower() in assistant_reply.lower()
                for cant_assist in CANNOT_ASSIST_PHRASES
            ):
                if len(models) <= 1:
                    raise RuntimeError("No models left to assist with prompt.")
                logger.warning(
                    "Assistant cannot assist; trying next model(s): {}", models[1:]
                )
                models = models[1:]
                continue

            if finish_reason == "length":
                logger.info(
                    "Finish reason 'length' encountered; continuing conversation"
                )
                convo = deepcopy(convo)
                convo.append({"role": "assistant", "content": assistant_reply})
                convo.append(
                    {"role": "user", "content": "Continue EXACTLY where we left off"}
                )
                continue

            if finish_reason == "content_filter":
                if len(models) <= 1:
                    raise RuntimeError(
                        "No more models to retry after content_filter finish reason"
                    )
                models = models[1:]
                continue

            if finish_reason != "stop":
                raise AssertionError(f"Unexpected finish reason: {finish_reason}")

            return assistant_reply, finish_reason

        raise RuntimeError("Exhausted all preferred models without successful response")

    def __get_response_stream(
        self,
        conversation: list[dict],
        preferred_models: list[str],
        use_paid_api: bool = False,
        options: Optional[RequestOptions] = None,
        stream_response: bool = True,
    ) -> Iterable[ResponseChunk]:
        if options is None:
            options = RequestOptions()

        selected = select_models(
            base_models=preferred_models,
            exhausted_models=self.exhausted_models,
            options=options,
            use_paid_api=use_paid_api,
        )
        model = selected[0]
        logger.info("Attempting stream with model: {}", model)

        additional_params: dict[str, Any] = {}
        if options.as_json:
            additional_params["response_format"] = {"type": "json_object"}

        try:
            stream = invoke_backend(
                client_manager=self.client_manager,
                conversation=conversation,
                model=model,
                stream_response=stream_response,
                additional_params=additional_params,
                use_paid_api=use_paid_api,
                MODEL_BY_BACKEND=MODEL_BY_BACKEND,
            )
        except Exception as e:
            logger.warning("API error encountered: {}. Delegating to handler.", e)
            stream = handle_api_error(
                e=e,
                conversation=conversation,
                preferred_models=selected,
                exhausted_models=self.exhausted_models,
                use_paid_api=use_paid_api,
                options=options,
                stream_response=stream_response,
                get_stream_callable=self.__get_response_stream,
            )
        return stream

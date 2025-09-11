from pathlib import Path
import re
from copy import deepcopy
from typing import Iterable, Union, Optional, Literal, Any

from loguru import logger
from tqdm import tqdm
from urllib3.exceptions import ResponseNotChunked

from llm.common.api_keys import api_keys
from llm.common.backend_invoker import invoke_backend, ResponseChunk
from llm.common.clients import LLMClientManager
from llm.common.routing.classification.model_classifier import LLMModel

from llm.constants import (
    CANNOT_ASSIST_PHRASES,
    MODELS_INCLUDING_CHAIN_THOUGHT,
    MODEL_BY_BACKEND,
)
from llm.common.error_handler import handle_api_error
from llm.common.model_selector import select_models
from llm.common.request_options import RequestOptions
from llm.common.response import decode_json_from_message, recalculate_finish_reason
from main_components.common.types import Platform
from llm.common.routing.model_router import ModelRouter
from llm.utils import load_and_prepare_prompts
from main_components.common.types import PromptItem


class BaseLLM:
    def __init__(
        self,
        prompt_json_template_path: Path,
        previous_storyline: str,
        platform_name: Platform,
    ):
        # Main input variables
        self.prompt_json_template_path = prompt_json_template_path
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name

        # Github models and OpenAI API keys
        self.github_api_keys: list[str] = api_keys.extract_github_keys()
        self.openai_api_keys: list[str] = api_keys.extract_openai_keys()

        self.client_manager = LLMClientManager(
            github_api_keys=self.github_api_keys, openai_api_keys=self.openai_api_keys
        )

        self.model_router = ModelRouter(
            github_api_keys=self.github_api_keys,
            openai_api_keys=self.openai_api_keys,
        )
        self.model_router.initialize_model_classifiers(models_to_scan=5)


        self.active_backend: Optional[Literal["openai", "azure"]] = None
        self.using_paid_api = False

    def _clean_chain_of_thought(self, model: str, assistant_reply: str) -> str:
        if model in MODELS_INCLUDING_CHAIN_THOUGHT:
            return re.sub(
                r"<think>.*?</think>", "", assistant_reply, flags=re.DOTALL
            ).strip()
        return assistant_reply

    def generate_dict_from_prompts(self) -> dict:
        prompt_items: list[PromptItem] = load_and_prepare_prompts(
            prompt_json_template_path=self.prompt_json_template_path,
            previous_storyline=self.previous_storyline,
        )

        last_reply: Union[str, dict] = ""

        # For each model in the ordered list: then we do this
        for prompt_item in tqdm(
            prompt_items, desc="Generating text with AI", total=len(prompt_items)
        ):
            # TODO: Assume model router is implemented and see where do I need it in the base llm (smart)
            # TODO: at some point, I would like to tell modelrouter to use api instead of free github models (just in case)
            model = self.model_router.get_best_available_model(prompt_item=prompt_items[0])

            # TODO: Use ModelRouter
            conversation = [
                {"role": "system", "content": prompt_item.system_prompt},
                {"role": "user", "content": prompt_item.prompt},
            ]

            options = RequestOptions(as_json=prompt_item.output_as_json)


            assistant_reply, finish_reason = self._get_model_response(
                conversation=conversation,
                options=options,
                model=model
            )
        return decode_json_from_message(message=last_reply)

    def _get_model_response(
        self,
        conversation: list[dict],
        options: RequestOptions,
        model: LLMModel
    ) -> tuple[str, str]:

        assistant_reply = ""
        finish_reason: Optional[str] = None

        convo = conversation
        # TODO: Use ModelRouter

        logger.info("Using model: {}", model.identifier)

        try:
            stream = self.__get_response_stream(
                conversation=convo,
                model=model,
                options=options,
                stream_response=True,
            )
        except Exception as e:
            # Here it was use handle_api_error, but we want to handle those errors using the Model router somehow
            raise


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

            if current_finish_reason is not None:
                finish_reason = current_finish_reason

        # TODO: Use ModelRouter
        non_exhausted = [
            m for m in selected_models if m not in self.exhausted_models
        ]
        used_model = non_exhausted[0] if non_exhausted else selected_models[0]
        # TODO: Use ModelRouter
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
            # continue

        if finish_reason == "length":
            logger.info(
                "Finish reason 'length' encountered; continuing conversation"
            )
            convo = deepcopy(convo)
            convo.append({"role": "assistant", "content": assistant_reply})
            convo.append(
                {"role": "user", "content": "Continue EXACTLY where we left off"}
            )
            # continue
        # TODO: Use ModelRouter
        if finish_reason == "content_filter":
            if len(models) <= 1:
                raise RuntimeError(
                    "No more models to retry after content_filter finish reason"
                )
            models = models[1:]
            # continue

        if finish_reason != "stop":
            raise AssertionError(f"Unexpected finish reason: {finish_reason}")

        return assistant_reply, finish_reason

        raise RuntimeError("Exhausted all preferred models without successful response")

    def __get_response_stream(
        self,
        conversation: list[dict[str, str]],
        preferred_models: list[str],
        use_paid_api: bool = False,
        options: Optional[RequestOptions] = None,
        stream_response: bool = True,
    ) -> Iterable[ResponseChunk]:
        if options is None:
            options = RequestOptions()
        # TODO: Use ModelRouter
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

from pathlib import Path

import sys


# Add the project root to sys.path to make modules importable
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from copy import deepcopy
from typing import Union, Optional, Literal


from loguru import logger
from tqdm import tqdm


from llm.common.api_keys import api_keys
from llm.common.routing.classification.model_classifier import LLMModel

from llm.constants import (
    CANNOT_ASSIST_PHRASES,
)
from llm.common.response import decode_json_from_message, recalculate_finish_reason
from main_components.common.types import Platform
from llm.common.routing.model_router import ModelRouter
from llm.utils import load_and_prepare_prompts, _clean_chain_of_thought
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

        # Model Router, returns 1 model at a time
        self.model_router = ModelRouter(
            github_api_keys=self.github_api_keys,
            openai_api_keys=self.openai_api_keys,
        )
        self.model_router.initialize_model_classifiers(models_to_scan=5)

        self.active_backend: Optional[Literal["openai", "azure"]] = None
        self.using_paid_api = False

    def generate_dict_from_prompts(self) -> dict:
        prompt_items: list[PromptItem] = load_and_prepare_prompts(
            prompt_json_template_path=self.prompt_json_template_path,
            previous_storyline=self.previous_storyline,
        )

        last_reply: str = ""

        for prompt_item in tqdm(
            prompt_items, desc="Generating text with AI", total=len(prompt_items)
        ):
            # TODO: at some point, I would like to tell modelrouter to use api instead of free github models (just in case)
            model = self.model_router.get_best_available_model(prompt_item=prompt_item)
            conversation = [
                {"role": "system", "content": prompt_item.system_prompt},
                {"role": "user", "content": prompt_item.prompt},
            ]
            output_as_json = prompt_item.output_as_json

            assistant_reply, finish_reason = model.get_model_response(
                conversation=conversation, output_as_json=output_as_json
            )
            last_reply = assistant_reply
            # If the model was exhausted, mark it as such
            # TODO: handle finish_reason properly
        return decode_json_from_message(message=last_reply)

    # def _get_response_stream(
    #     self,
    #     conversation: list[dict[str, str]],
    #     model: LLMModel,
    #     options: RequestOptions,
    #     use_paid_api: bool = False,
    #     stream_response: bool = True,
    # ) -> Iterable[ResponseChunk]:
    # additional_params: dict[str, Any] = {}
    # if options.as_json:
    #     additional_params["response_format"] = {"type": "json_object"}
    # try:
    #     stream = invoke_backend(
    #         conversation=conversation,
    #         model=model.identifier,
    #         use_paid_api=use_paid_api,
    #         stream_response=stream_response,
    #         additional_params=additional_params,
    #         github_api_keys=self.github_api_keys,
    #         openai_api_keys=self.openai_api_keys,
    #     )
    # except Exception as e:
    #     logger.warning("API error encountered: {}. Delegating to handler.", e)
    #     stream = handle_api_error(
    #         e=e,
    #         conversation=conversation,
    #         model=model,
    #         use_paid_api=use_paid_api,
    #         stream_response=stream_response,
    #         options=options,
    #         get_stream_callable=self._get_response_stream,
    #     )
    # return stream


if __name__ == "__main__":
    import sys
    from pathlib import Path
    from main_components.common.types import Platform

    # Add the project root to sys.path to make modules importable
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    # Example usage: Replace with your actual paths and values
    prompt_path = Path(
        r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\meta\inputs\laura_vigne.json"
    )  # Update to a valid prompt JSON file path
    storyline = "Once upon a time..."
    platform = Platform.META  # Update to the desired platform

    llm = BaseLLM(
        prompt_json_template_path=prompt_path,
        previous_storyline=storyline,
        platform_name=platform,
    )
    result = llm.generate_dict_from_prompts()
    print("Generated result:", result)

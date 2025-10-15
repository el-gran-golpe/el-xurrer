from pathlib import Path
from tqdm import tqdm
from loguru import logger

from llm.api_keys import api_keys
from llm.utils.response import decode_json_from_message
from main_components.common.types import Platform
from llm.routing.model_router import ModelRouter
from llm.utils.utils import load_and_prepare_prompts
from main_components.common.types import PromptItem


class BaseLLM:
    def __init__(
        self,
        prompt_json_template_path: Path,
        previous_storyline: str,
        platform_name: Platform,
        model_router: ModelRouter,
    ):
        # Main input variables
        self.prompt_json_template_path = prompt_json_template_path
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name

        self.model_router = model_router

    def generate_dict_from_prompts(self) -> dict:
        prompt_items: list[PromptItem] = load_and_prepare_prompts(
            prompt_json_template_path=self.prompt_json_template_path,
            previous_storyline=self.previous_storyline,
        )
        cache: dict[str, str] = {}
        last_reply: str = ""

        for prompt_item in tqdm(
            prompt_items, desc="Generating text with AI", total=len(prompt_items)
        ):
            prompt_item.replace_prompt_placeholders(cache=cache)

            assistant_reply = self.model_router.get_response(prompt_item=prompt_item)
            logger.info("Assistant reply: {}", assistant_reply)

            if prompt_item.cache_key:
                cache[prompt_item.cache_key] = assistant_reply
            last_reply = assistant_reply

        return decode_json_from_message(message=last_reply)

    def generate_simple_text(self, prompt: str) -> str:
        # TODO: Do we really need all of this info for a simple text generation?
        prompt_item = PromptItem(
            system_prompt="You are a helpful assistant for {day} storyline summaries.",
            prompt=prompt,
            output_as_json=False,
            cache_key="storyline_summary",
            is_sensitive_content=False,
        )
        prompt_item.system_prompt = prompt_item.system_prompt.replace(
            "{day}", "storyline"
        )

        response = self.model_router.get_response(prompt_item=prompt_item)
        return response.strip()


if __name__ == "__main__":
    # Example usage: Replace with your actual paths and values
    prompt_path = Path(
        r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\meta\inputs\laura_vigne.json"
        # "/home/yoncarlosmaria/Desktop/repos/el-xurrer/resources/laura_vigne/meta/inputs/laura_vigne.json"
    )  # Update to a valid prompt JSON file path
    storyline = "Once upon a time..."
    platform = Platform.META  # Update to the desired platform

    github_api_keys: list[str] = api_keys.extract_github_keys()
    openai_api_keys: list[str] = api_keys.extract_openai_keys()

    model_router = ModelRouter(
        github_api_keys=github_api_keys,
        openai_api_keys=openai_api_keys,
    )
    # None means scan all available models
    model_router.initialize_model_classifiers(models_to_scan=None)

    llm = BaseLLM(
        prompt_json_template_path=prompt_path,
        previous_storyline=storyline,
        platform_name=platform,
        model_router=model_router,
    )
    result = llm.generate_dict_from_prompts()
    print("Generated result:", result)

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
    ):
        # Main input variables
        self.prompt_json_template_path = prompt_json_template_path
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name

        # GitHub models and OpenAI API keys
        self.github_api_keys: list[str] = api_keys.extract_github_keys()
        self.openai_api_keys: list[str] = api_keys.extract_openai_keys()

        # Model Router, returns 1 model at a time
        self.model_router = ModelRouter(
            github_api_keys=self.github_api_keys,
            openai_api_keys=self.openai_api_keys,
        )
        self.model_router.initialize_model_classifiers(models_to_scan=None)

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


if __name__ == "__main__":
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

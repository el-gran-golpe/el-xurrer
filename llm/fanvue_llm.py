import json
from typing import Union

from llm.common.base_llm import BaseLLM
from llm.common.constants import DEFAULT_PREFERRED_MODELS
from llm.utils.utils import get_closest_monday


class FanvueLLM(BaseLLM):
    def __init__(
        self, preferred_models: Union[list[str], str] = DEFAULT_PREFERRED_MODELS
    ):
        super().__init__(preferred_models=preferred_models)

    def generate_fanvue_planning(
        self,
        prompt_template_path: str,
        previous_storyline: str,  # Can be an empty string if no initial conditions
    ) -> dict:
        with open(prompt_template_path, "r", encoding="utf-8") as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        lang = prompt_template["lang"]

        # Calculate the day and replace placeholders in the prompts
        monday_date = get_closest_monday().strftime("%Y-%m-%d")
        monday = "Monday" if lang == "en" else "Lunes"
        day = f"{monday} {monday_date}"

        # Insert variables into the prompt text
        prompts[0]["prompt"] = prompts[0]["prompt"].format(
            previous_storyline=previous_storyline
        )

        for prompt in prompts:
            if "system_prompt" in prompt:
                prompt["system_prompt"] = prompt["system_prompt"].format(day=day)

        # Generate the planning using the language model
        planning = self._generate_dict_from_prompts(
            prompts=prompts,
            preferred_models=self.preferred_models,
            desc="Generating Fanvue platform planning",
        )

        return planning

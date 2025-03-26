import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS
from llm.utils.utils import get_closest_monday


class FanvueLLM(BaseLLM):
    def __init__(self, preferred_models: list | tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_fanvue_planning(
        self, prompt_template_path: str, previous_storyline: str = ""
    ) -> dict:
        """
        Generates a planning for Fanvue platform content.

        :param prompt_template_path: Path to the prompt template file.
        :param previous_storyline: The storyline from the previous season (not used for Fanvue).
        :return: A dictionary containing the structured posts for uploading.
        """
        assert os.path.isfile(prompt_template_path), (
            f"Planning template not found: {prompt_template_path}"
        )

        with open(prompt_template_path, "r", encoding="utf-8") as file:
            prompt_template = json.load(file)

        prompts = prompt_template.get("prompts", [])
        lang = prompt_template.get("lang", "en")
        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        # Calculate the day and replace placeholders in the prompts if needed
        monday_date = get_closest_monday().strftime("%Y-%m-%d")
        monday = "Monday" if lang == "en" else "Lunes"
        day = f"{monday} {monday_date}"

        # Format any prompt variables if needed (not using previous_storyline for Fanvue)
        if len(prompts) > 1 and "system_prompt" in prompts[1]:
            prompts[1]["system_prompt"] = prompts[1]["system_prompt"].format(day=day)

        # Generate the planning using the language model
        planning = self._generate_dict_from_prompts(
            prompts=prompts,
            preferred_models=self.preferred_models,
            desc="Generating Fanvue platform planning",
        )

        return planning

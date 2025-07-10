import json
from pathlib import Path
from typing import Any, Union

from llm.common.base_llm import BaseLLM
from llm.common.constants import DEFAULT_PREFERRED_MODELS
from llm.utils.utils import get_closest_monday


class MetaLLM(BaseLLM):
    """LLM interface for generating Meta platform planning."""

    def __init__(
        self, preferred_models: Union[list[str], str] = DEFAULT_PREFERRED_MODELS
    ):
        super().__init__(preferred_models=preferred_models)

    def generate_meta_planning(
        self,
        prompt_template_path: Path,
        previous_storyline: str,
    ) -> dict[str, Any]:
        # Open and load the prompt template JSON file
        path = Path(prompt_template_path)
        with path.open("r", encoding="utf-8") as file:
            prompt_template = json.load(file)

        # Extract the list of prompts and language setting from the template
        prompts = prompt_template["prompts"]
        lang = prompt_template.get("lang", "en")

        # Compute the closest Monday's date and localize the weekday name
        monday_date = get_closest_monday().strftime("%Y-%m-%d")
        monday = "Monday" if lang == "en" else "Lunes"
        day = f"{monday} {monday_date}"

        # Fill in the previous storyline for the first prompt
        prompts[0]["prompt"] = prompts[0]["prompt"].format(
            previous_storyline=previous_storyline
        )

        # For each prompt, fill in the {day} placeholder
        for prompt in prompts:
            if "system_prompt" in prompt:
                prompt["system_prompt"] = prompt["system_prompt"].format(day=day)

        # Generate the planning dictionary using the prompts and return it
        return self._generate_dict_from_prompts(
            prompts=prompts,
            preferred_models=self.preferred_models,
            desc="Generating Meta platform planning",
        )

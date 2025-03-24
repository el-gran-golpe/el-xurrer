import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS
from utils.utils import get_closest_monday

class MetaLLM(BaseLLM):
    def __init__(self, preferred_models: list | tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_meta_planning(self, prompt_template_path: str, previous_storyline: str) -> dict:
        """
        Generates a 1-week Meta platform planning for the AI influencer's content.
        Works with both Instagram and Facebook content.
        
        :param prompt_template_path: Path to the prompt template file.
        :param previous_storyline: The storyline from the previous season.
        :return: A dictionary containing the structured posts for uploading.
        """
        assert os.path.isfile(prompt_template_path), f"Planning template not found: {prompt_template_path}"

        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        lang = prompt_template["lang"]
        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        # Calculate the day and replace placeholders in the prompts
        monday_date = get_closest_monday().strftime('%Y-%m-%d')
        monday = 'Monday' if lang == 'en' else 'Lunes'
        day = f"{monday} {monday_date}"

        # Insert variables into the prompt text
        prompts[0]['prompt'] = prompts[0]['prompt'].format(previous_storyline=previous_storyline)
        # TODO: this have to be done using the cache or placeholders method
        prompts[1]['system_prompt'] = prompts[1]['system_prompt'].format(day=day)

        # Generate the planning using the language model
        planning = self._generate_dict_from_prompts(
            prompts=prompts,
            preferred_models=self.preferred_models,
            desc="Generating Meta platform planning"
        )

        return planning

import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS
from tqdm import tqdm
from utils.utils import get_closest_monday
import re



class YoutubeLLM(BaseLLM):
    def __init__(self, preferred_models: list|tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_script(self, prompt_template_path: str, theme_prompt: str,
                        title: str, duration: int = 5) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(duration, (int, float)) and duration > 0, "Duration must be a positive number"

        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template["prompts"]
        prompts_definition[0]['prompt'] = prompts_definition[0]['prompt'].format(prompt=theme_prompt, duration=duration)

        return self._generate_dict_from_prompts(prompts=prompts_definition, preferred_models=self.preferred_models,
                                                desc="Generating script")

    def generate_youtube_planning(self, prompt_template_path: str, list_count: int = 6) -> dict:
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(list_count, int) and list_count > 0, "Videos count must be a positive integer"

        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        system_prompt = prompt_template.pop('system_prompt', None)
        prompts = prompt_template["prompts"]
        lang = prompt_template["lang"]
        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        monday_date = get_closest_monday().strftime('%Y-%m-%d')
        monday = 'Lunes' if lang == 'es' else 'Monday'
        day = f"{monday} {monday_date}"
        prompts[0]['prompt'] = prompts[0]['prompt'].format(list_count=list_count)
        prompts[1]['system_prompt'] = prompts[1]['system_prompt'].format(day=day)

        planning = self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models,
                                                    desc="Generating planning")
        return planning


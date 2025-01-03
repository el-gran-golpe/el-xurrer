from __future__ import annotations
import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS
from tqdm import tqdm

from utils.exceptions import InvalidScriptException
from utils.utils import get_closest_monday, generate_ids_in_script, check_script_validity
import re
from loguru import logger



class YoutubeLLM(BaseLLM):
    def __init__(self, preferred_models: list|tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_script(self, prompt_template_path: str, theme_prompt: str,
                        duration: int = 5, retries: int = 3) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(duration, (int, float)) and duration > 0, "Duration must be a positive number"

        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template["prompts"]
        prompts_definition[0]['prompt'] = prompts_definition[0]['prompt'].format(prompt=theme_prompt, duration=duration)
        prompts_definition[1]['prompt'] = prompts_definition[1]['prompt'].replace('{duration}', str(duration))

        for retry in range(retries):
            script = self._generate_dict_from_prompts(prompts=prompts_definition, preferred_models=self.preferred_models,
                                                    desc="Generating script")
            script = generate_ids_in_script(script = script)
            try:
                check_script_validity(script=script)
                break
            except AssertionError as e:
                logger.error(f"Error generating script: {e}. Retry {retry + 1}/{retries}")
        else:
            raise InvalidScriptException(f"Error generating script after {retries} retries")

        return script

    def generate_youtube_planning(self, prompt_template_path: str, list_count: int = 6) -> dict:
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(list_count, int) and list_count > 0, "Videos count must be a positive integer"

        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

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


import os
import json
from llm.base_llm import BaseLLM

from utils.utils import get_closest_monday



class YoutubeLLM(BaseLLM):
    def __init__(self, preferred_models: list|tuple = ('gpt-4o', 'gpt-4o-mini')):
        super().__init__(preferred_models=preferred_models)

    def generate_script(self, prompt_template_path: str, theme_prompt: str, thumbnail_text: str,
                        title: str, duration: int = 5, base_model: str = None) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(duration, (int, float)) and duration > 0, "Duration must be a positive number"

        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        system_prompt = prompt_template.pop('system_prompt', None)
        prompts = prompt_template["prompts"]
        force_models = prompt_template.get('force_models', {})
        force_models = {int(k): v for k, v in force_models.items()}

        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        prompts[0] = prompts[0].format(duration=duration, prompt=theme_prompt)
        prompts[3] = prompts[3].format(thumbnail_text=thumbnail_text)
        prompts[4] = prompts[4].replace('{thumbnail_text}', thumbnail_text).replace('{title}', title)

        return self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models, desc="Generating script",
                                                system_prompt=system_prompt,
                                                improvement_prompts=(1,))

    def generate_youtube_planning(self, prompt_template_path: str, video_count: int, base_model: str = None) -> dict:
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(video_count, int) and video_count > 0, "Videos count must be a positive integer"

        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        system_prompt = prompt_template.pop('system_prompt', None)
        prompts = prompt_template["prompts"]
        lang = prompt_template["lang"]
        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        monday_date = get_closest_monday().strftime('%Y-%m-%d')
        monday = 'Lunes' if lang == 'es' else 'Monday'

        prompts[0] = prompts[0].format(video_count=video_count)
        prompts[1] = prompts[1].format(day_of_week=monday, date=monday_date)

        planning = self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models,
                                                    system_prompt=system_prompt,
                                                    desc="Generating planning")
        return planning

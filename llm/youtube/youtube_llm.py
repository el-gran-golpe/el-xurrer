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

    def generate_script(self, prompt_template_path: str, theme_prompt: str, thumbnail_text: str,
                        title: str, duration: int = 5, base_model: str = None) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(duration, (int, float)) and duration > 0, "Duration must be a positive number"

        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template["prompts"]
        prompts_definition[0]['prompt'] = prompts_definition[0]['prompt'].format(prompt=theme_prompt, duration=duration)

        return self._generate_dict_from_prompts(prompts=prompts_definition, preferred_models=self.preferred_models,
                                                desc="Generating script")

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


    def _replace_prompt_placeholders(self, prompt: str, cache: dict[str, str]) -> str:
        """
        Replace the placeholders in the prompt with the values in the cache
        :param prompt: The prompt to replace the placeholders
        :param cache: The cache with the values to replace
        :return: The prompt with the placeholders replaced
        """
        placeholders = re.findall(r'{(\w+)}', prompt)
        for placeholder in placeholders:
            assert placeholder in cache, f"Placeholder '{placeholder}' not found in the cache"
            prompt = prompt.replace(f'{{{placeholder}}}', cache[placeholder])
        return prompt

    def _generate_dict_from_prompts(self, prompts: list[dict], preferred_models: list = None,
                                    desc: str = "Generating") -> dict:

        if preferred_models is None:
            assert len(self.preferred_models) > 0, "No preferred models found"
            preferred_models = self.preferred_models

        cache = {}

        # Loop through each prompt and get a response
        for i, prompt_definition in tqdm(enumerate(prompts), desc=desc, total=len(prompts)):
            assert all(key in prompt_definition for key in ('prompt', 'cache_key')), "Invalid prompt definition"
            prompt, cache_key = prompt_definition['prompt'], prompt_definition['cache_key']
            system_prompt = prompt_definition.get('system_prompt', None)
            conversation = []
            if system_prompt is not None:
                conversation.append({'role': 'system', 'content': system_prompt})
            prompt = self._replace_prompt_placeholders(prompt=prompt, cache=cache)
            conversation.append({'role': 'user', 'content': prompt})

            # Get the assistant's response
            assistant_reply, finish_reason = self.get_model_response(conversation=conversation,
                                                                     preferred_models=preferred_models)

            # Add the assistant's response to the cache
            cache[cache_key] = assistant_reply


        assert isinstance(assistant_reply, str) and len(assistant_reply) > 0, "Assistant response not found"
        # Decode the JSON object for the last assistant_reply
        output_dict = self.decode_json_from_message(message=assistant_reply)
        return output_dict
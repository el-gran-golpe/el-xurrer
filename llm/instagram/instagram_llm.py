import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS

class InstagramLLM(BaseLLM):
    def __init__(self, preferred_models: list | tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_storyline(self, prompt_template_path: str, previous_storyline: str = "", duration: int = 30) -> dict:
        """
        Generates a storyline for the AI influencer's Instagram content.
        :param prompt_template_path: Path to the prompt template file.
        :param previous_storyline: The storyline from the previous season.
        :param duration: Duration of the storyline in days.
        :return: A dictionary containing the structured posts for uploading.
        """
        assert os.path.isfile(prompt_template_path), f"Storyline template not found: {prompt_template_path}"

        # Load the prompt template
        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template['prompts']
        cache = {
            "previous_storyline": previous_storyline
        }

        for prompt_def in prompts_definition:
            # Replace placeholders in system_prompt and prompt
            if 'system_prompt' in prompt_def:
                prompt_def['system_prompt'] = self._replace_prompt_placeholders(prompt_def['system_prompt'], cache)
            if 'prompt' in prompt_def:
                prompt_def['prompt'] = self._replace_prompt_placeholders(prompt_def['prompt'], cache)

            # Generate the response for the current prompt
            assistant_reply, finish_reason = self.get_model_response(
                conversation=[
                    {'role': 'system', 'content': prompt_def['system_prompt']} if 'system_prompt' in prompt_def else {},
                    {'role': 'user', 'content': prompt_def['prompt']}
                ],
                preferred_models=self.preferred_models
            )

            # Add the assistant's reply to the cache using the cache_key
            cache_key = prompt_def.get('cache_key')
            if cache_key:
                cache[cache_key] = assistant_reply.strip()

        # The final output is the 'json_posts' from the cache
        output_json = cache.get('json_posts')
        if output_json:
            try:
                output_dict = json.loads(output_json)
                return output_dict
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse the assistant's final response as JSON: {e}")
        else:
            raise ValueError("No 'json_posts' found in the assistant's responses.")

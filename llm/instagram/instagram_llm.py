import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS


class InstagramLLM(BaseLLM):
    def __init__(self, preferred_models: list|tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_image_carousel(self, prompt_template_path: str) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

        raise NotImplementedError("Yon-Kaptain should implement the method for building the 'prompts' for this case")

        output_dict = self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models,
                                                       desc="Generating image carousel",
                                                       system_prompt=system_prompt)
        return output_dict


    def generate_story(self, prompt_template_path: str) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

        raise NotImplementedError("Yon-Kaptain should implement the method for building the 'prompts' for this case")

        output_dict = self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models,
                                                       desc="Generating story",
                                                       system_prompt=system_prompt)

        return output_dict
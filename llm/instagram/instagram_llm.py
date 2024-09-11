import os
import json
from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS


class InstagramLLM(BaseLLM):
    def __init__(self, preferred_models: list | tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_image_carousel(self, prompt_template_path: str) -> dict:
        """
        Generates an image carousel for an Instagram post.
        :param prompt_template_path: Path to the prompt template file.
        :return: A dictionary containing the generated image carousel.
        """
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

        # Load the prompt template
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        system_prompt = prompt_template.get("system_prompt", None)

        # Generate the image carousel using language models
        output_dict = self._generate_dict_from_prompts(
            prompts=prompts, 
            preferred_models=self.preferred_models,
            desc="Generating image carousel",
            system_prompt=system_prompt
        )

        return output_dict

    def generate_story(self, prompt_template_path: str) -> dict:
        """
        Generates a story for Instagram.
        :param prompt_template_path: Path to the prompt template file.
        :return: A dictionary containing the generated Instagram story.
        """
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

        # Load the prompt template
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        system_prompt = prompt_template.get("system_prompt", None)

        # Generate the story using language models
        output_dict = self._generate_dict_from_prompts(
            prompts=prompts, 
            preferred_models=self.preferred_models,
            desc="Generating story",
            system_prompt=system_prompt
        )

        return output_dict

    def generate_single_post(self, post_theme: str, image_description: str, hashtags: list = None) -> dict:
        """
        Generates a single Instagram post (caption and hashtags).
        :param post_theme: The theme for this post (e.g., AI in daily life).
        :param image_description: Description of the image content for the post.
        :param hashtags: Optional list of hashtags for the post.
        :return: A dictionary with the generated caption, hashtags, and image description.
        """
        prompt_template_path = os.path.join('.', 'llm', 'instagram', 'prompts', 'post.json')
        assert os.path.isfile(prompt_template_path), f"Post template not found: {prompt_template_path}"

        # Load the prompt template for post generation
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template['prompts']
        prompts_definition[0]['prompt'] = prompts_definition[0]['prompt'].format(
            post_theme=post_theme, image_description=image_description
        )

        # Generate the post content using language models
        post_data = self._generate_dict_from_prompts(
            prompts=prompts_definition, 
            preferred_models=self.preferred_models, 
            desc="Generating Instagram post"
        )

        # If hashtags are not provided, generate them from the post data
        if not hashtags:
            hashtags = post_data.get('hashtags', [])

        return {
            "caption": post_data['caption'],
            "hashtags": hashtags,
            "image_description": image_description
        }

    def generate_storyline(self, theme_prompt: str, duration: int = 30) -> dict:
        """
        Generates a storyline for the AI influencer's Instagram content.
        :param theme_prompt: Main theme of the Instagram content.
        :param duration: Duration of the storyline in days.
        :return: A dictionary containing the storyline for each day.
        """
        prompt_template_path = os.path.join('.', 'llm', 'instagram', 'prompts', 'storyline.json')
        assert os.path.isfile(prompt_template_path), f"Storyline template not found: {prompt_template_path}"

        # Load the prompt template for storyline generation
        with open(prompt_template_path, 'r') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template['prompts']
        prompts_definition[0]['prompt'] = prompts_definition[0]['prompt'].format(
            theme_prompt=theme_prompt, duration=duration
        )

        # Generate the storyline using language models
        storyline = self._generate_dict_from_prompts(
            prompts=prompts_definition, 
            preferred_models=self.preferred_models, 
            desc="Generating Instagram storyline"
        )

        return storyline

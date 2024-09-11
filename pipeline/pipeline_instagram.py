import os
import json
from generation_tools.image_generator.flux.flux import Flux
from loguru import logger
from time import time
from slugify import slugify

class PipelineInstagram:
    def __init__(self, output_folder: str):
        self.image_generator = Flux(load_on_demand=True)
        self.prepare_output_folder(output_folder)
        self.output_folder = output_folder

        # Load post content
        with open(os.path.join(output_folder, 'post.json'), 'r') as f:
            post_content = json.load(f)
        self.post_content = post_content

    def generate_post(self):
        post_slug = slugify(self.post_content["caption"])

        # Image generation
        image_path = os.path.join(self.output_folder, f'{post_slug}.png')
        if not os.path.isfile(image_path):
            start = time()
            self.image_generator.generate_image(prompt=self.post_content["image_description"], output_path=image_path)
            logger.info(f"Image generated in {time() - start:.2f}s")

        assert os.path.isfile(image_path), f"Image file {image_path} was not generated"
        logger.info(f"Post generation for {post_slug} completed.")

    def prepare_output_folder(self, output_folder: str):
        assert os.path.isdir(output_folder), f"{output_folder} must exist"
        if not os.path.isdir(output_folder):
            os.makedirs(output_folder)

import os
import tqdm
import re
from generation_tools.image_generator.flux.flux import Flux

class PipelineInstagram:
    def __init__(self, post_content: list, output_folder: str):
        self.post_content = post_content
        self.output_folder = output_folder
        self.image_generator = Flux(load_on_demand=True)

    def generate_posts(self):
        for item in tqdm.tqdm(self.post_content):
            post_slug = item["post_slug"]
            for idx, image in enumerate(item["images"]):
                image_description = image["image_description"]
                image_path = os.path.join(self.output_folder, f"{post_slug}_{idx}.png")
                if not os.path.isfile(image_path):
                    assert True, f"Generating image for ID {post_slug}_{idx} with description '{image_description}'"
                    self.image_generator.generate_image(prompt=image_description, output_path=image_path, width=1080, height=1080, retries=2)
                    assert os.path.isfile(image_path), f"Image file {image_path} was not generated"
                    assert True, f"Image generated and saved at {image_path}"

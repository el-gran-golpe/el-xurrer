import sys
import os
from uuid import uuid4
import json
from time import time
from tqdm import tqdm
from slugify import slugify
from loguru import logger

# Add the parent directory to the sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from generation_tools.image_generator.flux.flux import Flux

class InstagramContentGenerator:
    def __init__(self, output_folder: str):
        
        self.output_folder = output_folder
        self.image_generator = Flux(load_on_demand=True)
        self.prepare_output_folder(output_folder=output_folder)

    def generate_content(self, input_json: str):
        with open(input_json, 'r', encoding='utf-8') as f:
            content = json.load(f)
        
        base_description = content["base_description"]
        posts = content["posts"]

        for detail in tqdm(posts, desc="Generating Instagram Content"):
            post_date = detail["date"]
            post_id = f"{post_date}_{slugify(detail['caption'])[:15]}_{str(uuid4())[:4]}"
            post_folder = os.path.join(self.output_folder, post_date)

            if not os.path.isdir(post_folder):
                os.makedirs(post_folder)

            images_folder = os.path.join(post_folder, 'images')
            if not os.path.isdir(images_folder):
                os.makedirs(images_folder)
            
            image_paths = []
            for i, image_prompt in enumerate(detail["image_prompts"]):
                full_prompt = f"{base_description} {image_prompt}"
                image_path = os.path.join(images_folder, f"image_{i+1}.png")
                start = time()
                self.image_generator.generate_image(prompt=full_prompt, output_path=image_path)
                logger.info(f"Image {i+1} for {post_date} generated in {time() - start:.2f}s")
                image_paths.append(image_path)

            # Save the caption and location with UTF-8 encoding to handle special characters
            with open(os.path.join(post_folder, 'caption.txt'), 'w', encoding='utf-8') as caption_file:
                caption_file.write(detail["caption"])
            
            with open(os.path.join(post_folder, 'location.txt'), 'w', encoding='utf-8') as location_file:
                location_file.write(detail["location"])

            logger.info(f"Generated content for {post_date}: {len(image_paths)} images saved.")

    def prepare_output_folder(self, output_folder: str):
        if not os.path.isdir(output_folder):
            os.makedirs(output_folder)
        logger.info(f"Output folder prepared: {output_folder}")

if __name__ == '__main__':
    output_folder = 'instagram_profiles/laura_vigne'
    generator = InstagramContentGenerator(output_folder=output_folder)
    input_json = 'instagram_profiles/laura_vigne_content.json'  # Ensure correct path to your JSON file
    generator.generate_content(input_json=input_json)

import os
import json
from slugify import slugify
from tqdm import tqdm

from loguru import logger
from main_components.base_main import BaseMain
from main_components.constants import Platform
from utils.exceptions import WaitAndRetryError
from time import sleep
from generation_tools.image_generator.flux import Flux


class PublicationsGenerator(BaseMain):
    """Universal publications generator for creating content across different platforms."""

    def __init__(
        self,
        platform_name,
        template_profiles,
        llm_module_path=None,
        llm_class_name=None,
        llm_method_name=None,
    ):
        """
        Initialize the publications generator.

        Args:
            platform_name: Name of the platform (meta, fanvue, etc.)
            llm_module_path: (Optional) Path to the LLM module
            llm_class_name: (Optional) Name of the LLM class
            llm_method_name: (Optional) Name of the generation method
        """
        super().__init__(platform_name)
        self.template_profiles = template_profiles
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name

        # Initialize image generator (lazy loading)
        self.image_generator = None

    def _get_image_generator(self):
        """Get or initialize the image generator."""
        if self.image_generator is None:
            self.image_generator = Flux(load_on_demand=True)
        return self.image_generator

    def create_publication_directories(
        self, profile_name, json_data_planning, output_folder
    ):
        """Create directory structure for publications."""
        self.create_directory(output_folder)

        # Create folders for each week and day
        for week_key, week_data in json_data_planning.items():
            week_folder = os.path.join(output_folder, week_key)
            self.create_directory(week_folder)

            for day_data in week_data:
                day_folder = os.path.join(week_folder, f"day_{day_data['day']}")
                self.create_directory(day_folder)

                # Create captions.txt file
                captions = "\n\n".join([pub["caption"] for pub in day_data["posts"]])
                captions_file_path = os.path.join(day_folder, "captions.txt")
                self.write_to_file(captions, captions_file_path)

                # Create upload_times.txt file
                upload_times = "\n".join(
                    [pub["upload_time"] for pub in day_data["posts"]]
                )
                upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
                self.write_to_file(upload_times, upload_times_file_path)

        return output_folder

    # TODO: put comment separator

    def generate_images(self, publication_content, output_folder):
        """Generate images for publications based on platform."""
        if self.platform_name == Platform.META:
            self._generate_meta_images(publication_content, output_folder)
        elif self.platform_name == Platform.FANVUE:
            self._generate_fanvue_images(publication_content, output_folder)
        else:
            raise ValueError(f"Unsupported platform: {self.platform_name}")

    def _generate_meta_images(
        self, publication_content: list[dict], output_folder: str
    ):
        """Generate images for Meta platforms (Instagram/Facebook)."""
        for item in publication_content:
            post_slug = item["post_slug"]
            for idx, image in enumerate(item["images"]):
                image_description = image["image_description"]
                image_path = os.path.join(output_folder, f"{post_slug}_{idx}.png")

                if not os.path.isfile(image_path):
                    logger.info(
                        f"Generating image for ID {post_slug}_{idx} with description '{image_description}'"
                    )

                    # Get or initialize the image generator
                    image_generator = self._get_image_generator()

                    # Generate the image
                    image_generator.generate_image(
                        prompt=image_description,
                        output_path=image_path,
                        width=1080,
                        height=1080,
                    )
                    assert os.path.isfile(image_path), (
                        f"Image file {image_path} was not generated"
                    )
                    logger.success(f"Image generated and saved at {image_path}")

    def _generate_fanvue_images(self, publication_content, output_folder):
        """Generate images for Fanvue platform."""
        # Similar to _generate_meta_images but with Fanvue-specific customizations
        # For now, we'll use the same implementation as Meta
        self._generate_meta_images(publication_content, output_folder)

    def generate_publications_from_planning(
        self, profile_name, planning_file_path, output_folder
    ):
        """Generate publications for a specific profile based on planning data."""
        # Print profile name with colors
        print(f"\033[1;36mProcessing profile: \033[1;33m{profile_name}\033[0m")

        # Load the planning data
        with open(planning_file_path, "r", encoding="utf-8") as file:
            json_data_planning = json.load(file)

        # Create directory structure
        self.create_publication_directories(
            profile_name, json_data_planning, output_folder
        )

        # Generate publications for the planning data
        for week, days in tqdm(json_data_planning.items(), desc="Processing weeks"):
            week_folder = os.path.join(output_folder, week)

            for day_data in tqdm(days, desc=f"Processing days in {week}"):
                day_number = day_data["day"]
                day_folder = os.path.join(week_folder, f"day_{day_number}")

                for publication_data in day_data["posts"]:
                    publication_title = publication_data.get("title", "")
                    publication_slug = (
                        slugify(publication_title)
                        if publication_title
                        else f"publication_{day_number}"
                    )
                    caption = publication_data.get("caption", "")
                    hashtags = publication_data.get("hashtags", [])
                    upload_time = publication_data.get("upload_time", "")

                    # Prepare the publication content
                    publication_content = [
                        {
                            "post_title": publication_title,
                            "post_slug": publication_slug,
                            "caption": caption,
                            "hashtags": hashtags,
                            "upload_time": upload_time,
                            "images": [],
                        }
                    ]

                    # Add each image's description to the publication content
                    for image in publication_data.get("images", []):
                        publication_content[0]["images"].append(
                            {"image_description": image.get("image_description", "")}
                        )

                    # Generate images with retry mechanism
                    for retrial in range(25):
                        try:
                            # Directly call our integrated image generation method
                            self.generate_images(
                                publication_content=publication_content,
                                output_folder=day_folder,
                            )
                            break
                        except WaitAndRetryError as e:
                            sleep_time = e.suggested_wait_time
                            hours, minutes, seconds = (
                                sleep_time // 3600,
                                (sleep_time // 60) % 60,
                                sleep_time % 60,
                            )
                            for _ in tqdm(
                                range(100),
                                desc=f"Waiting {hours}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}",
                            ):
                                sleep(sleep_time / 100)

    def generate(self):
        """Main method to generate publications."""

        for profile in self.template_profiles:
            # Define output folder path
            planning_file_name = "".join(
                [word[0] for word in profile.name.split("_")]
            )  # THOUGHTS: This could be added in the Profile itself
            planning_file_path = os.path.join(
                profile.platform_info[self.platform_name].outputs_path,
                planning_file_name + "_planning.json",
            )

            output_folder = os.path.join(
                profile.platform_info[self.platform_name].outputs_path, "publications"
            )

            self.generate_publications_from_planning(
                profile.name, planning_file_path, output_folder
            )
